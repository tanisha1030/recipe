import streamlit as st
import json, sqlite3, re, io, base64
from pathlib import Path
from typing import List, Dict, Any
from difflib import get_close_matches
from fractions import Fraction
from PIL import Image

# ---------- CONFIG ----------
st.set_page_config(page_title="Smart Recipe Generator", layout="wide", initial_sidebar_state="expanded")

BASE = Path(__file__).parent
DATA_PATH = BASE / "recipes.json"
DB_PATH = BASE / "data.db"

# ---------- CONSTANTS ----------
NON_VEG_INGREDIENTS = {"egg", "chicken", "fish", "meat", "pork", "beef", "shrimp", "tuna", "salmon"}

SUBSTITUTIONS = {
    "butter": ["oil", "margarine"],
    "milk": ["soy milk", "almond milk", "water"],
    "egg": ["flaxseed", "banana (mashed)"],
    "yogurt": ["sour cream", "buttermilk"],
    "sugar": ["honey", "maple syrup", "stevia"]
}

COMMON_INGREDIENTS = [
    "tomato", "onion", "garlic", "potato", "carrot", "broccoli", "chicken",
    "beef", "fish", "egg", "cheese", "milk", "butter", "bread", "rice",
    "pasta", "flour", "sugar", "salt", "pepper", "oil", "lettuce",
    "cucumber", "bell pepper", "mushroom", "lemon", "lime", "apple",
    "banana", "strawberry", "spinach", "avocado", "basil", "parsley"
]

# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (recipe_id TEXT PRIMARY KEY, added_ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ratings (recipe_id TEXT PRIMARY KEY, rating INTEGER, rated_ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()

# ---------- LOAD DATA ----------
@st.cache_data(show_spinner=False)
def load_recipes() -> List[Dict[str, Any]]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------- SCALING ----------
def _parse_number_prefix(s: str):
    s = s.strip()
    m = re.match(r"^(\d+)\s+(\d+/\d+)\b(.*)$", s)
    if m:
        whole = int(m.group(1))
        frac = Fraction(m.group(2))
        rest = m.group(3).strip()
        return float(whole + frac), rest
    m = re.match(r"^(\d+/\d+)\b(.*)$", s)
    if m:
        frac = Fraction(m.group(1))
        rest = m.group(2).strip()
        return float(frac), rest
    m = re.match(r"^(\d+(\.\d+)?)(?:\s*([a-zA-Z\/]+))?\s*(.*)$", s)
    if m:
        num = float(m.group(1))
        unit = m.group(3) or ""
        rest = m.group(4).strip()
        if unit and (rest == "" or not rest.startswith(unit)):
            rest = (unit + " " + rest).strip()
        return num, rest
    return None, s

def scale_ingredients(ingredients: List[str], original_servings: int, new_servings: int) -> List[str]:
    scaled = []
    orig = int(original_servings or 1)
    new = int(new_servings or orig)
    ratio = new / orig if orig else 1
    for ing in ingredients:
        try:
            num, rest = _parse_number_prefix(ing)
            if num is None:
                scaled.append(f"{ing} (x{ratio:.2f})" if ratio != 1 else ing)
            else:
                scaled_num = round(num * ratio, 2)
                scaled.append(f"{scaled_num} {rest}".strip())
        except Exception:
            scaled.append(f"{ing} (x{ratio:.2f})" if ratio != 1 else ing)
    return scaled

def suggest_substitutions(ingredient: str):
    ingredient = (ingredient or "").lower()
    if ingredient in SUBSTITUTIONS:
        return SUBSTITUTIONS[ingredient]
    close = get_close_matches(ingredient, SUBSTITUTIONS.keys(), n=1, cutoff=0.7)
    return SUBSTITUTIONS[close[0]] if close else []

# ---------- MATCHING ----------
def match_recipes(available_ingredients: List[str], recipes: List[Dict],
                  dietary=None, difficulty=None, max_time=None, max_results=8):
    available = set(i.strip().lower() for i in available_ingredients if i.strip())
    results = []
    for r in recipes:
        req = set(map(str.lower, r.get("ingredients", [])))
        if dietary in ("vegetarian", "vegan") and req & NON_VEG_INGREDIENTS:
            continue
        if dietary and dietary not in [d.lower() for d in r.get("dietary", [])]:
            continue
        if difficulty and r.get("difficulty", "").lower() != difficulty:
            continue
        if max_time and r.get("time_minutes", 0) > max_time:
            continue
        exact_matches = req & available
        if not exact_matches:
            continue
        score = len(exact_matches) + len(exact_matches) / max(1, len(req))
        results.append((score, r))
    seen = set()
    deduped = []
    for s, r in sorted(results, key=lambda x: x[0], reverse=True):
        norm = re.sub(r"\(.*?\)", "", r["title"].lower()).strip()
        if norm in seen: continue
        seen.add(norm)
        deduped.append(r)
        if len(deduped) >= max_results: break
    return deduped

# ---------- FAVORITES ----------
def add_favorite(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO favorites (recipe_id) VALUES (?)", (recipe_id,))
    conn.commit(); conn.close()

def remove_favorite(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM favorites WHERE recipe_id=?", (recipe_id,))
    conn.commit(); conn.close()

def set_rating(recipe_id, rating):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ratings (recipe_id, rating) VALUES (?,?)", (recipe_id, int(rating)))
    conn.commit(); conn.close()

def get_user_ratings():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT recipe_id, rating FROM ratings")
    data = {r[0]: r[1] for r in c.fetchall()}
    conn.close(); return data

def get_favorites():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT recipe_id FROM favorites ORDER BY added_ts DESC")
    res = [r[0] for r in c.fetchall()]
    conn.close(); return res

# ---------- IMAGE INGREDIENT DETECTION ----------
def recognize_ingredients_from_image(image: Image.Image) -> List[str]:
    """Simulated ingredient recognition — in production, call ML API here."""
    try:
        st.image(image, caption="Uploaded Image", use_column_width=True)
        st.info("🧠 Simulated ingredient detection — select visible ingredients:")
        detected = st.multiselect(
            "Select detected ingredients:",
            options=COMMON_INGREDIENTS,
            default=[],
            help="Select the ingredients you see in the photo"
        )
        return detected
    except Exception as e:
        st.error(f"Error recognizing image: {e}")
        return []

# ---------- MAIN ----------
def main():
    init_db()
    st.title("🍽️ Smart Recipe Generator — Now with Image Recognition")
    st.caption("Generate recipes from ingredients or from a photo of your ingredients.")

    recipes = load_recipes()

    tab1, tab2 = st.tabs(["🔍 Search by Ingredients", "📸 From Photo"])

    # --- Tab 1: Manual ingredient input ---
    with tab1:
        with st.form("search_form"):
            col1, col2 = st.columns([2, 1])
            with col1:
                ing_text = st.text_input("Enter ingredients (comma-separated)", placeholder="e.g. tomato, onion, cheese")
                selected = st.multiselect("Or select ingredients", sorted(COMMON_INGREDIENTS))
            with col2:
                servings = st.number_input("Servings", min_value=1, value=2, step=1)
                dietary = st.selectbox("Dietary", ["Any", "Vegetarian", "Vegan"])
                difficulty = st.selectbox("Difficulty", ["Any", "Easy", "Medium", "Hard"])
                max_time = st.slider("Max Time (min)", 5, 180, 60)
                max_results = st.slider("Max Results", 3, 12, 6)
            submitted = st.form_submit_button("Find Recipes 🚀")

        if submitted:
            all_ing = list({*(ing_text.lower().split(",") + selected)})
            if not all_ing or all_ing == ['']:
                st.warning("Please enter at least one ingredient.")
                return
            matches = match_recipes(all_ing, recipes, dietary if dietary!="Any" else None,
                                    difficulty if difficulty!="Any" else None, max_time, max_results)
            if not matches:
                st.info("No recipes found.")
            else:
                st.success(f"Found {len(matches)} recipes for {servings} servings.")
                for r in matches:
                    with st.expander(f"{r['title']} ({r.get('time_minutes','?')} min)"):
                        orig_serv = int(r.get("servings", 1) or 1)
                        scaled_ings = scale_ingredients(r.get("ingredients", []), orig_serv, servings)
                        st.markdown("**Ingredients:**")
                        for i in scaled_ings: st.write("- " + i)
                        st.markdown("**Instructions:**")
                        for idx, step in enumerate(r.get("steps", []), 1):
                            st.write(f"{idx}. {step}")

    # --- Tab 2: Image recognition ---
    with tab2:
        uploaded = st.file_uploader("Upload an image of your ingredients", type=["jpg", "jpeg", "png"])
        if uploaded:
            try:
                image = Image.open(uploaded)
                detected = recognize_ingredients_from_image(image)
                if detected:
                    st.success(f"Detected: {', '.join(detected)}")
                    servings = st.number_input("Servings for this photo", min_value=1, value=2, step=1)
                    if st.button("Find Recipes from Photo 🍲"):
                        matches = match_recipes(detected, recipes, max_results=6)
                        if matches:
                            for r in matches:
                                with st.expander(f"{r['title']} ({r.get('time_minutes','?')} min)"):
                                    orig_serv = int(r.get("servings", 1) or 1)
                                    scaled_ings = scale_ingredients(r.get("ingredients", []), orig_serv, servings)
                                    st.write("**Ingredients:**")
                                    for i in scaled_ings: st.write("- " + i)
                                    st.write("**Instructions:**")
                                    for idx, step in enumerate(r.get("steps", []), 1):
                                        st.write(f"{idx}. {step}")
                        else:
                            st.info("No recipes found for these ingredients.")
            except Exception as e:
                st.error(f"Error processing image: {e}")
        else:
            st.info("Upload an image to detect ingredients automatically.")

if __name__ == "__main__":
    main()
