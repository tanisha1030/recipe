
import streamlit as st
import json, sqlite3, math, re
from pathlib import Path
from typing import List, Dict, Any
from difflib import get_close_matches

st.set_page_config(page_title="Smart Recipe Generator", layout="centered", initial_sidebar_state="expanded")

BASE = Path(__file__).parent
DATA_PATH = BASE / "recipes.json"
DB_PATH = BASE / "data.db"

SUBSTITUTIONS = {
    "butter": ["oil", "margarine"],
    "milk": ["soy milk", "almond milk", "water"],
    "egg": ["flaxseed", "banana (mashed)"],
    "yogurt": ["sour cream", "buttermilk"],
    "sugar": ["honey", "maple syrup", "stevia"]
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (recipe_id TEXT PRIMARY KEY, added_ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ratings (recipe_id TEXT PRIMARY KEY, rating INTEGER, rated_ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()

@st.cache_data(show_spinner=False)
def load_recipes() -> List[Dict[str,Any]]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def match_recipes(available_ingredients: List[str], recipes: List[Dict], dietary=None, difficulty=None, max_time=None, max_results=8):
    available = set(i.strip().lower() for i in available_ingredients if i.strip())
    scored = []
    for r in recipes:
        if dietary and dietary not in [d.lower() for d in r.get("dietary", [])]:
            continue
        if difficulty and r.get("difficulty","").lower() != difficulty:
            continue
        if max_time and r.get("time_minutes",0) > max_time:
            continue
        req = set(i.lower() for i in r.get("ingredients",[]))
        common = len(req & available)
        missing = len(req - available)
        score = common - 0.4 * missing + (0.1 * min(available_ingredients.__len__(), len(req)))
        overlap = common / max(1, len(req))
        scored.append((score, overlap, common, missing, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item[-1] for item in scored[:max_results]]

def suggest_substitutions(ingredient: str):
    ingredient = ingredient.lower()
    # direct map
    if ingredient in SUBSTITUTIONS:
        return SUBSTITUTIONS[ingredient]
    # fuzzy match keys
    close = get_close_matches(ingredient, SUBSTITUTIONS.keys(), n=1, cutoff=0.7)
    if close:
        return SUBSTITUTIONS[close[0]]
    return []

def scale_ingredients(ingredients: List[str], original_servings:int, new_servings:int) -> List[str]:
    scaled = []
    ratio = new_servings / original_servings if original_servings else 1
    qty_re = re.compile(r"^(\d+(\.\d+)?)(\s?)([a-zA-Z\/]+)?\s*(.*)$")  # crude
    for ing in ingredients:
        m = qty_re.match(ing.strip())
        if m:
            num = float(m.group(1))
            rest = m.group(5)
            scaled_num = round(num * ratio, 2)
            unit = m.group(4) or ""
            scaled.append(f"{scaled_num} {unit} {rest}".strip())
        else:
            # no numeric quantity — return note
            scaled.append(f"{ing}  (adjust proportionally by {ratio}x)")
    return scaled

def add_favorite(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO favorites (recipe_id) VALUES (?)", (recipe_id,))
        conn.commit()
    finally:
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

def recommend_from_ratings(recipes, user_ratings, top_n=6):
    # simple rule-based suggestions: find cuisines/dietary similar to high-rated recipes
    liked = [rid for rid,r in user_ratings.items() if r>=4]
    if not liked:
        return []
    liked_meta = [next((rr for rr in recipes if rr["id"]==rid), None) for rid in liked]
    cuisines = {}
    diets = {}
    for m in liked_meta:
        if not m: continue
        cuisines[m.get("cuisine","unknown")] = cuisines.get(m.get("cuisine","unknown"),0)+1
        for d in m.get("dietary",[]):
            diets[d] = diets.get(d,0)+1
    scored = []
    for r in recipes:
        score = 0
        score += cuisines.get(r.get("cuisine","unknown"),0)
        for d in r.get("dietary",[]):
            score += diets.get(d,0)
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored if s[0]>0][:top_n]

# --- UI ---
def main():
    init_db()
    st.title("🍽️ Smart Recipe Generator — Full Version")
    st.markdown("Get recipe suggestions from ingredients, filters, serving-size adjust, image upload (stub), ratings & favorites.")

    recipes = load_recipes()

    # Top filters
    with st.form("search_form", clear_on_submit=False):
        cols = st.columns([2,1])
        with cols[0]:
            ing_text = st.text_input("Enter ingredients (comma-separated) or use the multi-select below:", placeholder="e.g. egg, milk, flour")
            common_list = sorted({i for r in recipes for i in r.get("ingredients",[])})[:60]
            selected = st.multiselect("Or select ingredients from list (fast)", options=common_list, default=[])
        with cols[1]:
            dietary = st.selectbox("Dietary preference", ["Any","Vegetarian","Vegan","Gluten-Free","None"])
            difficulty = st.selectbox("Difficulty", ["Any","Easy","Medium","Hard"])
            max_time = st.slider("Max cooking time (minutes)", 5, 240, 60)
            max_results = st.slider("Max results", 3, 12, 6)
        submitted = st.form_submit_button("Find Recipes 🚀")

    # Image upload (stubbed recognizer)
    st.markdown("### Or upload a photo of ingredients (image recognition is a demo/stub).")
    uploaded = st.file_uploader("Upload image (jpg/png)", type=["jpg","jpeg","png"])
    recognized_ings = []
    if uploaded:
        with st.spinner("Recognizing ingredients (demo)..."):
            # Demo: use filename keywords and a tiny heuristic
            name = uploaded.name.lower()
            for kw in ["egg","tomato","onion","potato","milk","cheese","garlic","chicken","broccoli","carrot","banana"]:
                if kw in name:
                    recognized_ings.append(kw)
            if not recognized_ings:
                # fallback: suggest few common pantry items
                recognized_ings = ["flour","salt","oil"]

    # combine inputs
    text_ings = [i.strip() for i in ing_text.split(",") if i.strip()]
    all_selected = list({*(text_ings + selected + recognized_ings)})

    # Filters normalization
    dietary_filter = None if dietary in ("Any","None") else dietary.lower()
    difficulty_filter = None if difficulty=="Any" else difficulty.lower()

    if submitted:
        if not all_selected:
            st.warning("Please provide at least one ingredient (text, list select, or upload an image).")
        else:
            with st.spinner("Computing matches..."):
                matches = match_recipes(all_selected, recipes, dietary=dietary_filter, difficulty=difficulty_filter, max_time=max_time, max_results=max_results)
            if not matches:
                st.info("No matches found. Try removing filters or adding more ingredients.")
            else:
                st.success(f"Found {len(matches)} recipes.")
                for r in matches:
                    with st.expander(f\"{r['title']} — {r.get('time_minutes','?')} min — {r.get('difficulty','?')}\"):
                        # show core recipe with serving adjuster and light controls
                        st.write(f\"**Cuisine:** {r.get('cuisine','N/A')}  •  **Dietary:** {', '.join(r.get('dietary',[]))}\")
                        orig_serv = r.get('servings',1)
                        new_serv = st.number_input(f\"Servings (orig {orig_serv})\", min_value=1, value=orig_serv, key=f\"serv_{r['id']}\")
                        ing_list = scale_ingredients(r.get('ingredients',[]), orig_serv, new_serv)
                        st.write(\"**Ingredients (scaled):**\")
                        for i in ing_list:
                            # show substitution hint
                            subs = suggest_substitutions(i.split()[0]) if i and isinstance(i,str) else []
                            if subs:
                                st.write(f\"- {i}  (substitutes: {', '.join(subs)})\")
                            else:
                                st.write(f\"- {i}\")
                        st.write(\"**Instructions:**\")
                        for idx,step in enumerate(r.get('steps',[]),1):
                            st.write(f\"{idx}. {step}\")
                        st.write(\"**Nutrition:**\")
                        for k,v in r.get('nutrition',{}).items():
                            st.write(f\"- {k}: {v}\")

                        # favorites & rating
                        cols = st.columns([1,1,1])
                        with cols[0]:
                            if st.button(\"Save Favorite\", key=f\"fav_{r['id']}\"):
                                add_favorite(r['id'])
                                st.success(\"Added to favorites\")
                        with cols[1]:
                            cur_ratings = get_user_ratings().get(r['id'], 0)
                            rating = st.selectbox(\"Rate (0-5)\", options=[0,1,2,3,4,5], index=cur_ratings, key=f\"rate_{r['id']}\")
                            if st.button(\"Submit Rating\", key=f\"rate_btn_{r['id']}\"):
                                set_rating(r['id'], rating)
                                st.success(\"Thanks for rating!\")
                        with cols[2]:
                            if st.button(\"Remove Favorite\", key=f\"unfav_{r['id']}\"):
                                remove_favorite(r['id'])
                                st.info(\"Removed from favorites\")

    # Sidebar: favorites, suggestions, quick filters
    st.sidebar.header(\"Your Favorites & Suggestions\")
    favs = get_favorites()
    if favs:
        recipes_map = {rr['id']: rr for rr in recipes}
        for fid in favs:
            r = recipes_map.get(fid)
            if r:
                st.sidebar.write(f\"- {r['title']} ({r.get('time_minutes','?')} min)\")
    else:
        st.sidebar.info(\"No favorites yet.\")

    # Suggestions based on ratings
    st.sidebar.markdown(\"---\")
    ur = get_user_ratings()
    recs = recommend_from_ratings(recipes, ur, top_n=6)
    if recs:
        st.sidebar.subheader(\"Recommended for you\")
        for rr in recs:
            st.sidebar.write(f\"- {rr['title']} ({rr.get('cuisine','')})\")
    else:
        st.sidebar.caption(\"Rate recipes to get personalized suggestions.\")

    st.sidebar.markdown(\"---\")
    st.sidebar.caption(\"This demo includes an image-upload stub for ingredient recognition. To enable real recognition, add an API key and use a Vision API (see README).\")


if __name__ == '__main__':
    main()
