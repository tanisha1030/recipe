
import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="Smart Recipe Generator", layout="centered")

DATA_PATH = Path(__file__).parent / "recipes.json"

@st.cache_data(show_spinner=False)
def load_recipes():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def match_recipes(available_ingredients, recipes, dietary=None, max_results=8):
    available = set(i.strip().lower() for i in available_ingredients if i.strip())
    scored = []
    for r in recipes:
        if dietary and dietary.lower() not in [d.lower() for d in r.get("dietary", [])]:
            continue
        req = set(i.lower() for i in r["ingredients"])
        common = len(req & available)
        score = common - 0.5 * max(0, len(req - available))
        overlap_ratio = common / max(1, len(req))
        scored.append((score, overlap_ratio, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item[-1] for item in scored[:max_results]]

def show_recipe(r):
    st.subheader(r["title"])
    st.caption(f"⏱ {r['time_minutes']} min • {r['difficulty']} • Serves {r.get('servings',1)}")
    st.write("**Ingredients:**", ", ".join(r["ingredients"]))
    st.write("**Instructions:**")
    for i, step in enumerate(r["steps"], 1):
        st.write(f"{i}. {step}")
    st.write("**Nutrition (per serving):**")
    for k, v in r.get("nutrition", {}).items():
        st.write(f"- {k.capitalize()}: {v}")
    st.markdown("---")

def main():
    st.title("🍽️ Smart Recipe Generator (Fast Version)")
    st.markdown("Enter your ingredients and dietary preference. The app will quickly suggest recipes that match.")

    recipes = load_recipes()

    col1, col2 = st.columns([2, 1])
    with col1:
        ing_text = st.text_area("Ingredients (comma-separated)", "eggs, milk, flour, tomato, onion", height=80)
    with col2:
        dietary = st.selectbox("Dietary preference", ["Any", "Vegetarian", "Vegan", "Gluten-Free", "None"])
        max_results = st.slider("Max results", 3, 12, 6)

    available_ingredients = [i.strip() for i in ing_text.split(",") if i.strip()]
    dietary_filter = None if dietary in ("Any", "None") else dietary

    if st.button("Find Recipes 🚀"):
        if not available_ingredients:
            st.warning("Please enter at least one ingredient.")
            return
        results = match_recipes(available_ingredients, recipes, dietary_filter, max_results=max_results)
        if not results:
            st.info("No matching recipes found.")
            return
        st.success(f"Found {len(results)} recipes.")
        for r in results:
            with st.expander(f"{r['title']} — {r['time_minutes']} min"):
                show_recipe(r)

    # Sidebar favorites
    st.sidebar.header("⭐ Favorites (Session Only)")
    favs = st.session_state.get("favorites", [])
    if favs:
        recipes_map = {r["id"]: r for r in recipes}
        for fid in favs:
            if fid in recipes_map:
                st.sidebar.write(f"- {recipes_map[fid]['title']}")
    else:
        st.sidebar.info("No favorites yet. Expand a recipe and add one.")

    st.sidebar.markdown("---")
    st.sidebar.caption("Optimized Streamlit demo for Smart Recipe Generator.")

if __name__ == "__main__":
    main()
