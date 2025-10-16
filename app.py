import streamlit as st
import json, sqlite3, re
from pathlib import Path
from typing import List, Dict, Any
from difflib import get_close_matches
from fractions import Fraction

st.set_page_config(page_title="Smart Recipe Generator", layout="centered", initial_sidebar_state="expanded")

BASE = Path(__file__).parent
DATA_PATH = BASE / "recipes.json"
DB_PATH = BASE / "data.db"

# Non-veg ingredients to exclude for vegetarian/vegan filters
NON_VEG_INGREDIENTS = {"egg", "chicken", "fish", "meat", "pork", "beef", "shrimp", "tuna", "salmon"}

SUBSTITUTIONS = {
    "butter": ["oil", "margarine"],
    "milk": ["soy milk", "almond milk", "water"],
    "egg": ["flaxseed", "banana (mashed)"],
    "yogurt": ["sour cream", "buttermilk"],
    "sugar": ["honey", "maple syrup", "stevia"]
}

# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (recipe_id TEXT PRIMARY KEY, added_ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ratings (recipe_id TEXT PRIMARY KEY, rating INTEGER, rated_ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()

# ---------- DATA ----------
@st.cache_data(show_spinner=False)
def load_recipes() -> List[Dict[str, Any]]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------- UTILITIES ----------
def _parse_number_prefix(s: str):
    """Extract leading numeric quantity (supports fractions, decimals, and mixed numbers)."""
    s = s.strip()
    # mixed number: 1 1/2
    m = re.match(r"^(\d+)\s+(\d+/\d+)\b(.*)$", s)
    if m:
        whole = int(m.group(1))
        frac = Fraction(m.group(2))
        rest = m.group(3).strip()
        return float(whole + frac), rest
    # simple fraction: 1/2
    m = re.match(r"^(\d+/\d+)\b(.*)$", s)
    if m:
        frac = Fraction(m.group(1))
        rest = m.group(2).strip()
        return float(frac), rest
    # decimal or integer
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
    """
    Scales ingredient lines intelligently. If no numeric quantity exists,
    adds proportional note (x2, x0.5, etc.)
    """
    scaled = []
    try:
        orig = int(original_servings) if original_servings else 1
    except Exception:
        orig = 1
    try:
        new = int(new_servings) if new_servings else orig
    except Exception:
        new = orig

    ratio = new / orig if orig else 1.0

    for ing in ingredients:
        try:
            num, rest = _parse_number_prefix(ing)
            if num is None:
                if ratio != 1:
                    scaled.append(f"{ing} (x{ratio:.2f})")
                else:
                    scaled.append(ing)
            else:
                scaled_num = round(num * ratio, 2)
                scaled.append(f"{scaled_num} {rest}".strip())
        except Exception:
            if ratio != 1:
                scaled.append(f"{ing} (x{ratio:.2f})")
            else:
                scaled.append(ing)
    return scaled


def suggest_substitutions(ingredient: str):
    ingredient = (ingredient or "").lower()
    if ingredient in SUBSTITUTIONS:
        return SUBSTITUTIONS[ingredient]
    close = get_close_matches(ingredient, SUBSTITUTIONS.keys(), n=1, cutoff=0.7)
    if close:
        return SUBSTITUTIONS[close[0]]
    return []


# ---------- MATCHING ----------
def match_recipes(available_ingredients: List[str], recipes: List[Dict],
                  dietary=None, difficulty=None, max_time=None, max_results=8):
    available = set(i.strip().lower() for i in available_ingredients if i.strip())
    results = []

    for r in recipes:
        req = set(r.get("ingredients", []))

        # strict dietary enforcement
        if dietary in ("vegetarian", "vegan"):
            if req & NON_VEG_INGREDIENTS:
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

        common = len(exact_matches)
        overlap = common / max(1, len(req))
        if overlap < 0.25 and common < 1:
            continue
        score = common + overlap
        results.append((score, r))

    # ✅ Deduplicate by normalized title (ignore "(v1)", "(v4)", etc.)
    seen_titles = set()
    deduped = []
    for score, r in sorted(results, key=lambda x: x[0], reverse=True):
        norm_title = re.sub(r"\(.*?\)", "", r["title"].lower()).strip()
        if norm_title in seen_titles:
            continue
        seen_titles.add(norm_title)
        deduped.append(r)
        if len(deduped) >= max_results:
            break

    return deduped


# ---------- FAVORITES / RATINGS ----------
def add_favorite(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO favorites (recipe_id) VALUES (?)", (recipe_id,))
    conn.commit()
    conn.close()

def remove_favorite(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM favorites WHERE recipe_id=?", (recipe_id,))
    conn.commit()
    conn.close()

def set_rating(recipe_id, rating):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ratings (recipe_id, rating) VALUES (?,?)", (recipe_id, int(rating)))
    conn.commit()
    conn.close()

def get_user_ratings():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT recipe_id, rating FROM ratings")
    res = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return res

def get_favorites():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT recipe_id FROM favorites ORDER BY added_ts DESC")
    res = [row[0] for row in c.fetchall()]
    conn.close()
    return res


# ---------- RECOMMENDATIONS ----------
def recommend_from_ratings(recipes, user_ratings, top_n=6):
    liked = [rid for rid, r in user_ratings.items() if r >= 4]
    if not liked:
        return []
    liked_meta = [next((rr for rr in recipes if rr["id"] == rid), None) for rid in liked]
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
    st.title("🍽️ Smart Recipe Generator — Final Version")
    st.markdown("Improved matching, deduplication, and global serving scaling.")

    recipes = load_recipes()

    with st.form("search_form"):
        col1, col2 = st.columns([2, 1])
        with col1:
            ing_text = st.text_input("Enter ingredients (comma-separated)", placeholder="e.g. bread, tomato, cheese")
            common_list = sorted({i for r in recipes for i in r.get("ingredients", [])})[:80]
            selected = st.multiselect("Or select ingredients", options=common_list, default=[])
        with col2:
            servings = st.number_input("Servings (default 1)", min_value=1, value=1, step=1)
            dietary = st.selectbox("Dietary preference", ["Any", "Vegetarian", "Vegan", "Gluten-Free", "None"])
            difficulty = st.selectbox("Difficulty", ["Any", "Easy", "Medium", "Hard"])
            max_time = st.slider("Max cooking time (min)", 5, 240, 60)
            max_results = st.slider("Max results", 3, 12, 6)
        submitted = st.form_submit_button("Find Recipes 🚀")

    text_ings = [i.strip() for i in ing_text.split(",") if i.strip()]
    all_selected = list({*(text_ings + selected)})

    dietary_filter = None if dietary in ("Any", "None") else dietary.lower()
    difficulty_filter = None if difficulty == "Any" else difficulty.lower()

    if submitted:
        if not all_selected:
            st.warning("Please provide at least one ingredient.")
        else:
            with st.spinner("Matching recipes..."):
                matches = match_recipes(all_selected, recipes, dietary=dietary_filter,
                                        difficulty=difficulty_filter, max_time=max_time, max_results=max_results)
            if not matches:
                st.info("No matches found. Try other ingredients or remove filters.")
            else:
                st.success(f"Found {len(matches)} recipes (scaled for {servings} serving{'s' if servings>1 else ''}).")
                for r in matches:
                    with st.expander(f"{r['title']} — {r.get('time_minutes','?')} min — {r.get('difficulty','?')}"):
                        st.write(f"**Cuisine:** {r.get('cuisine','N/A')} • **Dietary:** {', '.join(r.get('dietary',[]))}")

                        orig_serv = r.get('servings', 1) or 1
                        try:
                            orig_serv = int(orig_serv)
                        except Exception:
                            orig_serv = 1
                        ing_list = scale_ingredients(r.get('ingredients', []), orig_serv, servings)

                        st.write("**Ingredients (scaled):**")
                        for i in ing_list:
                            word = (i.split()[0] if i else "").strip(",()")
                            subs = suggest_substitutions(word)
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

                        c1, c2, c3 = st.columns([1,1,1])
                        with c1:
                            if st.button("❤️ Save Favorite", key=f"fav_{r['id']}"):
                                add_favorite(r['id']); st.success("Added to favorites")
                        with c2:
                            cur_ratings = get_user_ratings().get(r['id'], 0)
                            idx = cur_ratings if isinstance(cur_ratings, int) and 0 <= cur_ratings <= 5 else 0
                            rating = st.selectbox("Rate (0–5)", [0,1,2,3,4,5], index=idx, key=f"rate_{r['id']}")
                            if st.button("Submit Rating", key=f"rate_btn_{r['id']}"):
                                set_rating(r['id'], rating); st.success("Thanks for rating!")
                        with c3:
                            if st.button("🗑️ Remove Favorite", key=f"unfav_{r['id']}"):
                                remove_favorite(r['id']); st.info("Removed from favorites")

    # Sidebar: favorites & recommendations (unchanged)
    st.sidebar.header("⭐ Favorites & Suggestions")
    favs = get_favorites()
    if favs:
        recipes_map = {r['id']: r for r in recipes}
        for fid in favs:
            if fid in recipes_map:
                st.sidebar.write(f"- {recipes_map[fid]['title']} ({recipes_map[fid].get('time_minutes','?')} min)")
    else:
        st.sidebar.info("No favorites yet.")
    st.sidebar.markdown("---")
    ur = get_user_ratings()
    recs = recommend_from_ratings(recipes, ur, top_n=6)
    if recs:
        st.sidebar.subheader("Recommended for you")
        for rr in recs:
            st.sidebar.write(f"- {rr['title']} ({rr.get('cuisine','')})")
    else:
        st.sidebar.caption("Rate recipes to get personalized suggestions.")

