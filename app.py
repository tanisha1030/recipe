import streamlit as st
import json
import sqlite3
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from difflib import get_close_matches
from fractions import Fraction
from datetime import datetime
import io
from PIL import Image
import base64

# ========== CONFIGURATION ==========
st.set_page_config(
    page_title="Smart Recipe Generator",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE = Path(__file__).parent
DATA_PATH = BASE / "recipes.json"
DB_PATH = BASE / "data.db"

# ========== CONSTANTS ==========
NON_VEG_INGREDIENTS = {
    "egg", "eggs", "chicken", "fish", "meat", "pork", "beef",
    "shrimp", "tuna", "salmon", "bacon", "ham", "turkey", "lamb",
    "duck", "crab", "lobster", "anchovy", "anchovies", "gelatin"
}

SUBSTITUTIONS = {
    "butter": ["oil", "margarine", "coconut oil", "ghee"],
    "milk": ["soy milk", "almond milk", "oat milk", "coconut milk"],
    "egg": ["flaxseed + water", "chia seeds + water", "applesauce", "banana"],
    "yogurt": ["sour cream", "buttermilk", "coconut yogurt"],
    "sugar": ["honey", "maple syrup", "agave", "stevia"],
    "flour": ["almond flour", "coconut flour", "oat flour", "rice flour"],
    "cream": ["coconut cream", "cashew cream", "evaporated milk"],
    "cheese": ["nutritional yeast", "vegan cheese", "tofu"],
    "soy sauce": ["tamari", "coconut aminos", "worcestershire sauce"],
    "vinegar": ["lemon juice", "lime juice", "white wine"]
}

COMMON_INGREDIENTS = [
    "tomato", "onion", "garlic", "potato", "carrot", "broccoli",
    "chicken", "beef", "fish", "egg", "cheese", "milk", "butter",
    "bread", "rice", "pasta", "flour", "sugar", "salt", "pepper",
    "oil", "lettuce", "cucumber", "bell pepper", "mushroom",
    "lemon", "lime", "apple", "banana", "orange", "strawberry",
    "spinach", "kale", "avocado", "ginger", "basil", "parsley"
]

# ========== DATABASE ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            recipe_id TEXT PRIMARY KEY,
            title TEXT,
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
    conn.close()

# ========== DATA ==========
@st.cache_data(show_spinner=False)
def load_recipes() -> List[Dict[str, Any]]:
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            recipes = json.load(f)
        return [r for r in recipes if 'id' in r and 'title' in r and 'ingredients' in r]
    except Exception as e:
        st.error(f"Error loading recipes: {e}")
        return []

# ========== INGREDIENT SCALING ==========
def _parse_number_prefix(s: str) -> Tuple[Optional[float], str]:
    """Extract leading numeric quantity (supports fractions, decimals, and mixed numbers)."""
    s = s.strip()
    # Mixed number e.g. 1 1/2
    m = re.match(r"^(\d+)\s+(\d+/\d+)\b(.*)$", s)
    if m:
        whole = int(m.group(1))
        frac = Fraction(m.group(2))
        rest = m.group(3).strip()
        return float(whole + frac), rest
    # Fraction
    m = re.match(r"^(\d+/\d+)\b(.*)$", s)
    if m:
        frac = Fraction(m.group(1))
        rest = m.group(2).strip()
        return float(frac), rest
    # Decimal or integer
    m = re.match(r"^(\d+(?:\.\d+)?)(.*)$", s)
    if m:
        num = float(m.group(1))
        rest = m.group(2).strip()
        return num, rest
    return None, s

def scale_ingredients(ingredients: List[str], original_servings: int, new_servings: int) -> List[str]:
    """Scale ingredients intelligently."""
    scaled = []
    try:
        ratio = new_servings / max(1, original_servings)
        for ing in ingredients:
            num, rest = _parse_number_prefix(ing)
            if num is not None:
                scaled_num = num * ratio
                if scaled_num.is_integer():
                    scaled_num = int(scaled_num)
                else:
                    scaled_num = round(scaled_num, 2)
                scaled.append(f"{scaled_num} {rest}".strip())
            else:
                scaled.append(f"{ing} (x{ratio:.1f})" if ratio != 1 else ing)
        return scaled
    except Exception:
        return ingredients

# ========== FAVORITES ==========
def add_favorite(recipe_id: str, title: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO favorites (recipe_id, title) VALUES (?, ?)", (recipe_id, title))
    conn.commit()
    conn.close()

def remove_favorite(recipe_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM favorites WHERE recipe_id=?", (recipe_id,))
    conn.commit()
    conn.close()

def get_favorites() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT recipe_id, title, added_ts FROM favorites ORDER BY added_ts DESC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "added": r[2]} for r in rows]

# ========== RATINGS ==========
def set_rating(recipe_id: str, rating: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ratings (recipe_id, rating) VALUES (?,?)", (recipe_id, rating))
    conn.commit()
    conn.close()

def get_ratings() -> Dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT recipe_id, rating FROM ratings")
    ratings = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return ratings

# ========== UI ==========
def display_recipe(recipe: Dict[str, Any], servings: int):
    st.markdown(f"### 🍴 {recipe['title']}")
    orig_servings = int(recipe.get("servings", 1) or 1)
    scaled_ingredients = scale_ingredients(recipe.get("ingredients", []), orig_servings, servings)

    st.caption(f"Original Servings: {orig_servings} → Adjusted for {servings} serving(s)")

    st.subheader("📝 Ingredients")
    for i in scaled_ingredients:
        st.markdown(f"- {i}")

    st.subheader("👨‍🍳 Instructions")
    for idx, step in enumerate(recipe.get("steps", []), 1):
        st.markdown(f"**Step {idx}:** {step}")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("❤️ Add Favorite", key=f"fav_{recipe['id']}"):
            add_favorite(recipe['id'], recipe['title'])
            st.success("Added to favorites!")
            st.rerun()
    with col2:
        rating_val = st.slider("Rate Recipe", 0, 5, get_ratings().get(recipe["id"], 0), key=f"rate_{recipe['id']}")
        if st.button("Save Rating", key=f"save_rate_{recipe['id']}"):
            set_rating(recipe['id'], rating_val)
            st.success("Rating saved!")
    with col3:
        if st.button("🗑️ Remove Favorite", key=f"unfav_{recipe['id']}"):
            remove_favorite(recipe['id'])
            st.info("Removed from favorites")
            st.rerun()

# ========== MAIN ==========
def main():
    init_db()
    st.title("🍽️ Smart Recipe Generator")
    recipes = load_recipes()
    if not recipes:
        st.error("No recipes found.")
        return

    with st.sidebar:
        st.header("⭐ Your Favorites")
        favs = get_favorites()
        if favs:
            for f in favs:
                st.write(f"**{f['title']}**")
                st.caption(f"Added on {f['added']}")
        else:
            st.info("No favorites yet!")

    servings = st.number_input("Select Servings", min_value=1, max_value=20, value=2, step=1)

    ing_input = st.text_input("Enter ingredients (comma-separated):", "tomato, onion, cheese")

    if st.button("Find Recipes"):
        ing_list = [i.strip().lower() for i in ing_input.split(",") if i.strip()]
        if not ing_list:
            st.warning("Please enter at least one ingredient.")
            return

        matches = [r for r in recipes if any(ing in " ".join(r["ingredients"]).lower() for ing in ing_list)]

        if not matches:
            st.info("No recipes found.")
        else:
            st.success(f"Found {len(matches)} recipes for {servings} serving(s):")
            for r in matches:
                with st.expander(f"{r['title']} ({r.get('time_minutes','?')} min)"):
                    display_recipe(r, servings)


if __name__ == "__main__":
    main()
