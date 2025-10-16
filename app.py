import streamlit as st
import json
import sqlite3
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from difflib import get_close_matches

# ---------- PAGE ----------
st.set_page_config(page_title="Smart Recipe Generator", layout="centered", initial_sidebar_state="expanded")

BASE = Path(__file__).parent
DATA_PATH = BASE / "recipes.json"
DB_PATH = BASE / "data.db"

# ---------- SUBSTITUTIONS (simple map) ----------
SUBSTITUTIONS = {
    "butter": ["oil", "margarine"],
    "milk": ["soy milk", "almond milk", "water"],
    "egg": ["flaxseed", "banana (mashed)"],
    "yogurt": ["sour cream", "buttermilk"],
    "sugar": ["honey", "maple syrup", "stevia"],
    "cheese": ["nutritional yeast", "vegan cheese"]
}

# ---------- DATABASE ----------
def init_db():
    """Create DB and tables if missing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                recipe_id TEXT PRIMARY KEY,
                added_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                recipe_id TEXT PRIMARY KEY,
                rating INTEGER,
                rated_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        st.error(f"Database init error: {e}")
    finally:
        try:
            conn.close()
        except:
            pass

# ---------- DATA LOADING ----------
@st.cache_data(show_spinner=False)
def load_recipes() -> List[Dict[str, Any]]:
    """Load recipes.json and return list of recipes. Expect each recipe to have keys:
       id, title, ingredients (list), steps (list), nutrition (dict), servings (int),
       difficulty, time_minutes, cuisine, dietary (list).
    """
    if not DATA_PATH.exists():
        st.warning("recipes.json not found in project folder. Please add it (required: min 20 recipes).")
        return []
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                st.error("recipes.json should contain a list of recipe objects.")
                return []
            return data
    except json.JSONDecodeError as e:
        st.error(f"Error parsing recipes.json: {e}")
        return []
    except Exception as e:
        st.error(f"Failed to load recipes: {e}")
        return []

# ---------- UTILITIES ----------
# regex to strip leading quantities and units like "1", "1/2", "1.5", "1 1/2", "2 tbsp"
_QTY_RE = re.compile(r"""
    ^\s*
    (?P<qty>(\d+(\.\d+)?)(\s*\d+/\d+)?|\d+/\d+)?    # mixed numbers, decimals, fractions
    (\s*(?P<unit>[a-zA-Z]+(\.?[a-zA-Z]*)?))?       # simple unit token
    \s*(?P<rest>.*)$
""", re.VERBOSE)

def normalize_ingredient_text(text: str) -> str:
    """Lowercase, strip punctuation and leading qty/unit to get the ingredient basename."""
    if not text:
        return ""
    text = text.strip().lower()
    m = _QTY_RE.match(text)
    if m:
        rest = m.group("rest") or text
    else:
        rest = text
    # remove parentheses contents and commas
    rest = re.sub(r"\(.*?\)", "", rest)
    rest = re.sub(r"[,.;:]", "", rest)
    # take first 3 words as the base, because some ingredients have descriptors
    parts = rest.split()
    return " ".join(parts[:3]).strip()

def extract_base_ingredient(ingredient_line: str) -> str:
    """Wrap normalize_ingredient_text for readability."""
    return normalize_ingredient_text(ingredient_line)

def suggest_substitutions(ingredient: str) -> List[str]:
    """Suggest substitutes for an ingredient base (case-insensitive)."""
    if not ingredient:
        return []
    base = normalize_ingredient_text(ingredient)
    # exact match
    if base in SUBSTITUTIONS:
        return SUBSTITUTIONS[base]
    # fuzzy match against keys
    close = get_close_matches(base, SUBSTITUTIONS.keys(), n=1, cutoff=0.7)
    if close:
        return SUBSTITUTIONS[close[0]]
    return []

def parse_quantity(ing_line: str) -> (Optional[float], str):
    """Attempt to extract a numeric quantity and remaining text; returns (qty, rest).
       Supports simple fractions like '1/2' and mixed numbers '1 1/2'.
    """
    line = ing_line.strip()
    m = _QTY_RE.match(line)
    if not m:
        return None, line
    qty_str = m.group("qty")
    rest = m.group("rest") or line
    if not qty_str:
        return None, rest.strip()
    # handle fraction or mixed number
    qty_str = qty_str.replace(" ", "")
    if "/" in qty_str:
        try:
            if qty_str.count("/") == 1 and qty_str[0].isdigit():
                # "1/2" or "3/2"
                num = float(sum(Fraction(q) for q in [qty_str]))
            else:
                num = float(eval(qty_str))  # fallback (rare)
        except Exception:
            try:
                num = float(Fraction(qty_str))
            except Exception:
                num = None
    else:
        try:
            num = float(qty_str)
        except Exception:
            num = None
    return num, rest.strip()

def scale_ingredients(ingredients: List[str], original_servings: int, new_servings: int) -> List[str]:
    """Scale numeric quantities in ingredient strings; fallback to proportional note if no quantity detected."""
    scaled = []
    if original_servings <= 0:
        original_servings = 1
    ratio = new_servings / original_servings
    for ing in ingredients:
        qty, rest = parse_quantity(ing)
        if qty is None:
            # no numeric quantity detected
            scaled.append(f"{ing} (adjust proportionally by {ratio:.2f}x)")
        else:
            # round nicely: if integer -> int, else 2 decimals
            new_qty = qty * ratio
            if abs(new_qty - round(new_qty)) < 1e-8:
                qty_str = str(int(round(new_qty)))
            else:
                qty_str = str(round(new_qty, 2))
            scaled.append(f"{qty_str} {rest}".strip())
    return scaled

# ---------- MATCHING ----------
def match_recipes(available_ingredients: List[str], recipes: List[Dict], dietary: Optional[str]=None,
                  difficulty: Optional[str]=None, max_time: Optional[int]=None, max_results=8):
    """Return best-matching recipes given available ingredients and filters.
       This algorithm:
         - normalizes available ingredient set (including expansions for known substitutions),
         - for each recipe counts exact matches and substitute matches,
         - penalizes missing ingredients,
         - returns top results (sorted by score then overlap).
    """
    available_norm = set(normalize_ingredient_text(i) for i in available_ingredients if i and i.strip())
    # expand available with known synonyms/substitutes (if user has 'oil', treat as possible 'butter' substitute)
    expanded = set(available_norm)
    for a in list(available_norm):
        for key, subs in SUBSTITUTIONS.items():
            # if user has a substitute that matches this key, add the key as 'available' for matching
            if any(normalize_ingredient_text(s) == a for s in subs):
                expanded.add(normalize_ingredient_text(key))
    scored = []
    for r in recipes:
        # filters
        if dietary:
            r_diets = [d.lower() for d in r.get("dietary", [])]
            if dietary.lower() not in r_diets:
                continue
        if difficulty:
            if r.get("difficulty", "").lower() != difficulty.lower():
                continue
        if max_time and r.get("time_minutes", 0) > max_time:
            continue

        req_ings = [normalize_ingredient_text(i) for i in r.get("ingredients", []) if i]
        if not req_ings:
            continue
        exact_matches = 0
        substitute_matches = 0
        missing = 0
        for req in req_ings:
            if req in expanded:
                exact_matches += 1
            else:
                # check if any substitution for this req exists in user's available list
                subs_for_req = SUBSTITUTIONS.get(req, [])
                if any(normalize_ingredient_text(s) in available_norm for s in subs_for_req):
                    substitute_matches += 1
                else:
                    missing += 1
        # score: exact matches weighted higher than substitutes, penalize missing
        score = (2.0 * exact_matches) + (1.0 * substitute_matches) - (0.5 * missing)
        overlap = exact_matches / max(1, len(req_ings))
        scored.append((score, overlap, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item[-1] for item in scored[:max_results]]

# ---------- FAVORITES / RATINGS (with error checks) ----------
def _with_conn(func):
    """Decorator to safely open/close db connection for simple operations."""
    def wrapper(*args, **kwargs):
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            res = func(conn, *args, **kwargs)
            return res
        except Exception as e:
            st.error(f"DB error: {e}")
            return None
        finally:
            if conn:
                conn.close()
    return wrapper

@_with_conn
def add_favorite(conn, recipe_id):
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO favorites (recipe_id) VALUES (?)", (recipe_id,))
    conn.commit()

@_with_conn
def remove_favorite(conn, recipe_id):
    c = conn.cursor()
    c.execute("DELETE FROM favorites WHERE recipe_id=?", (recipe_id,))
    conn.commit()

@_with_conn
def set_rating(conn, recipe_id, rating):
    try:
        r = int(rating)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO ratings (recipe_id, rating) VALUES (?,?)", (recipe_id, r))
        conn.commit()
    except ValueError:
        st.error("Rating must be an integer 0-5.")

@_with_conn
def get_user_ratings(conn) -> Dict[str, int]:
    c = conn.cursor()
    c.execute("SELECT recipe_id, rating FROM ratings")
    return {row[0]: row[1] for row in c.fetchall()}

@_with_conn
def get_favorites(conn) -> List[str]:
    c = conn.cursor()
    c.execute("SELECT recipe_id FROM favorites ORDER BY added_ts DESC")
    return [row[0] for row in c.fetchall()]

# ---------- RECOMMENDATIONS ----------
def recommend_from_ratings(recipes: List[Dict], user_ratings: Dict[str, int], top_n=6):
    """Recommend by looking at cuisines/dietary preferences of recipes the user rated 4 or 5."""
    liked = [rid for rid, r in user_ratings.items() if r >= 4]
    if not liked:
        return []
    liked_meta = [next((rr for rr in recipes if rr.get("id") == rid), None) for rid in liked]
    cuisines, diets = {}, {}
    for m in liked_meta:
        if not m:
            continue
        cuisines[m.get("cuisine", "unknown")] = cuisines.get(m.get("cuisine", "unknown"), 0) + 1
        for d in m.get("dietary", []):
            diets[d] = diets.get(d, 0) + 1
    scored = []
    for r in recipes:
        score = cuisines.get(r.get("cuisine", "unknown"), 0)
        for d in r.get("dietary", []):
            score += diets.get(d, 0)
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored if s[0] > 0][:top_n]

# ---------- MAIN APP ----------
def main():
    init_db()
    st.title("🍽️ Smart Recipe Generator — Fixed Version")
    st.markdown("Find recipes using ingredients, filters, serving-size scaling, substitutions, and a demo image upload.")

    recipes = load_recipes()
    if recipes and len(recipes) < 20:
        st.warning(f"Loaded {len(recipes)} recipes. Assignment asks for a minimum of 20 recipes. Add more for improved matching.")

    # --- Input Form ---
    with st.form("search_form"):
        col1, col2 = st.columns([2, 1])
        with col1:
            ing_text = st.text_input(
                "Enter ingredients (comma-separated)",
                placeholder="e.g. egg, milk, flour"
            )
            # build a fairly short common list for the selector
            common_list = sorted({i for r in recipes for i in r.get("ingredients", [])})[:80]
            selected = st.multiselect("Or select ingredients from list", options=common_list, default=[])
        with col2:
            dietary = st.selectbox("Dietary preference", ["Any", "Vegetarian", "Vegan", "Gluten-Free", "None"])
            difficulty = st.selectbox("Difficulty", ["Any", "Easy", "Medium", "Hard"])
            max_time = st.slider("Max cooking time (min)", 5, 240, 60)
            max_results = st.slider("Max results", 3, 12, 6)
        submitted = st.form_submit_button("Find Recipes 🚀")

    # --- Image upload (demo) ---
    st.markdown("### Or upload a photo of ingredients (demo image recognition)")
    uploaded = st.file_uploader("Upload image (jpg/png)", type=["jpg", "jpeg", "png"])
    recognized_ings = []
    if uploaded:
        with st.spinner("Recognizing ingredients (demo)..."):
            # very simple demo: check filename keywords; real app would call a Vision API
            name = uploaded.name.lower()
            demo_keywords = ["egg", "tomato", "onion", "potato", "milk", "cheese", "garlic",
                             "chicken", "broccoli", "carrot", "banana", "flour", "salt", "oil"]
            for kw in demo_keywords:
                if kw in name:
                    recognized_ings.append(kw)
            # fallback if filename doesn't contain keywords
            if not recognized_ings:
                recognized_ings = ["flour", "salt", "oil"]

    # Combine inputs
    text_ings = [i.strip() for i in ing_text.split(",") if i.strip()]
    all_selected = list(dict.fromkeys([*(text_ings + selected + recognized_ings)]))  # preserve unique order

    dietary_filter = None if dietary in ("Any", "None") else dietary.lower()
    difficulty_filter = None if difficulty == "Any" else difficulty.lower()

    if submitted:
        if not all_selected:
            st.warning("Please provide at least one ingredient (text, select, or image).")
        else:
            with st.spinner("Finding matching recipes..."):
                matches = match_recipes(all_selected, recipes, dietary=dietary_filter,
                                         difficulty=difficulty_filter, max_time=max_time, max_results=max_results)
            if not matches:
                st.info("No matches found. Try removing filters or adding ingredients.")
            else:
                st.success(f"Found {len(matches)} recipes.")
                for r in matches:
                    with st.expander(f"{r.get('title','Untitled')} — {r.get('time_minutes','?')} min — {r.get('difficulty','?')}"):
                        st.write(f"**Cuisine:** {r.get('cuisine','N/A')} • **Dietary:** {', '.join(r.get('dietary',[])) or 'None'}")
                        orig_serv = r.get('servings', 1) or 1
                        new_serv = st.number_input(f"Servings (orig {orig_serv})", min_value=1, value=orig_serv, key=f"serv_{r.get('id')}")
                        ing_list = scale_ingredients(r.get('ingredients', []), orig_serv, new_serv)
                        st.write("**Ingredients (scaled):**")
                        for i in ing_list:
                            base_ing = extract_base_ingredient(i)
                            subs = suggest_substitutions(base_ing)
                            if subs:
                                st.write(f"- {i}  (substitutes: {', '.join(subs)})")
                            else:
                                st.write(f"- {i}")
                        st.write("**Instructions:**")
                        for idx, step in enumerate(r.get('steps', []), 1):
                            st.write(f"{idx}. {step}")
                        st.write("**Nutrition:**")
                        for k, v in r.get('nutrition', {}).items():
                            st.write(f"- {k}: {v}")

                        # Favorites & rating controls
                        c1, c2, c3 = st.columns([1, 1, 1])
                        with c1:
                            if st.button("❤️ Save Favorite", key=f"fav_{r.get('id')}"):
                                add_favorite(r.get('id'))
                                st.toast("Added to favorites")
                        with c2:
                            user_ratings = get_user_ratings() or {}
                            cur_ratings = user_ratings.get(r.get('id'), 0)
                            rating = st.selectbox("Rate (0–5)", [0, 1, 2, 3, 4, 5], index=cur_ratings, key=f"rate_{r.get('id')}")
                            if st.button("Submit Rating", key=f"rate_btn_{r.get('id')}"):
                                set_rating(r.get('id'), rating)
                                st.toast("Thanks for rating!")
                        with c3:
                            if st.button("🗑️ Remove Favorite", key=f"unfav_{r.get('id')}"):
                                remove_favorite(r.get('id'))
                                st.toast("Removed from favorites")

    # --- Sidebar ---
    st.sidebar.header("⭐ Favorites & Suggestions")
    favs = get_favorites() or []
    if favs and recipes:
        recipes_map = {r['id']: r for r in recipes}
        for fid in favs:
            if fid in recipes_map:
                st.sidebar.write(f"- {recipes_map[fid]['title']} ({recipes_map[fid].get('time_minutes','?')} min)")
    else:
        st.sidebar.info("No favorites yet.")

    st.sidebar.markdown("---")
    ur = get_user_ratings() or {}
    recs = recommend_from_ratings(recipes, ur, top_n=6) if recipes else []
    if recs:
        st.sidebar.subheader("Recommended for you")
        for rr in recs:
            st.sidebar.write(f"- {rr.get('title','')} ({rr.get('cuisine','')})")
    else:
        st.sidebar.caption("Rate recipes to get personalized suggestions.")

    st.sidebar.markdown("---")
    st.sidebar.caption("Image recognition is a demo. Add an API key and call a Vision API to enable real detection.")

if __name__ == "__main__":
    main()
