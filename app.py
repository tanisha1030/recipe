import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="Smart Recipe Generator", layout="centered")

DATA_PATH = Path(__file__).parent / "recipes.json"


@st.cache_data
def load_recipes():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def match_recipes(available_ingredients, recipes, dietary=None, max_results=8):
    available = set([i.strip().lower() for i in available_ingredients if i.strip()])
    scored = []
    for r in recipes:
        if dietary and dietary.lower() not in [d.lower() for d in r.get("dietary", [])]:
            continue
        req = set([i.lower() for i in r["ingredients"]])
        common = len(req & available)
        score = common - 0.5 * max(0, len(req - available))  # prefer better overlap
        overlap_ratio = common / max(1, len(req))
        scored.append((score, overlap_ratio, common, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item[-1] for item in scored[:max_results]]


def main():
    st.title("🍽️ Smart Recipe Generator")
    st.markdown(
        "Enter the ingredients you have (comma-separated) and optionally select a dietary preference. "
        "The app will suggest matching recipes."
    )

    recipes = load_recipes()

    col1, col2 = st.columns([2, 1])
    with col1:
        ing_text = st.text_area(
            "Available ingredients (comma-separated)",
            value="eggs, milk, flour, tomato, onion",
            height=80,
        )
    with col2:
        dietary = st.selectbox(
            "Dietary preference", ["Any", "Vegetarian", "Vegan", "Gluten-Free", "None"]
        )
        max_results = st.slider("Max results", 3, 12, 6)

    available_ingredients = [i.strip() for i in ing_text.split(",") if i.strip()]
    dietary_filter = None if dietary in ("Any", "None") else dietary

    if st.button("Find recipes"):
        if not available_ingredients:
            st.warning("Please provide at least one ingredient.")
        else:
            matches = match_recipes(
                available_ingredients, recipes, dietary_filter, max_results=max_results
            )
            if not matches:
                st.info(
                    "No matching recipes found. Try removing the dietary filter or adding more ingredients."
                )
            else:
                st.success(f"Found {len(matches)} suggested recipes:")
                for r in matches:
                    with st.expander(
                        f"{r['title']} — {r['time_minutes']} min — Difficulty: {r['difficulty']}"
                    ):
                        st.markdown(f"**Ingredients:** {', '.join(r['ingredients'])}")
                        st.markdown(
                            f"**Servings:** {r.get('servings', 1)} — **Calories:** {r.get('nutrition', {}).get('calories', 'N/A')} kcal"
                        )

                        st.markdown("**Instructions:**")
                        for i, step in enumerate(r["steps"], 1):
                            st.write(f"{i}. {step}")

                        st.markdown("**Nutrition (per serving):**")
                        for k, v in r.get("nutrition", {}).items():
                            st.write(f"- {k.capitalize()}: {v}")

                        st.markdown("---")
                        colA, colB = st.columns(2)
                        with colA:
                            if st.button(f"❤️ Save Favorite ({r['id']})", key=f"fav_{r['id']}"):
                                favs = st.session_state.get("favorites", [])
                                if r["id"] not in favs:
                                    favs.append(r["id"])
                                    st.session_state["favorites"] = favs
                                    st.success("Saved to favorites!")
                                else:
                                    st.info("Already in favorites.")
                        with colB:
                            rating = st.slider(
                                f"Rate this recipe ({r['id']})",
                                0,
                                5,
                                0,
                                key=f"rate_{r['id']}",
                            )
                            if rating > 0:
                                st.session_state.setdefault("ratings", {})[r["id"]] = rating
                                st.write("⭐ Thanks for rating!")

    st.sidebar.header("Your Saved Favorites (Session)")
    favs = st.session_state.get("favorites", [])
    if favs:
        recipes_map = {r["id"]: r for r in recipes}
        for fid in favs:
            r = recipes_map.get(fid)
            if r:
                st.sidebar.write(f"- {r['title']} ({r['time_minutes']} min)")

    st.sidebar.markdown("---")
    st.sidebar.write(
        "**About:** Demo Streamlit app for Smart Recipe Generator. "
        "See README for deployment instructions."
    )


if __name__ == "__main__":
    main()
