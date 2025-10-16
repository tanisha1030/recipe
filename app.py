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

# Common ingredients that might appear in images
COMMON_INGREDIENTS = [
    "tomato", "onion", "garlic", "potato", "carrot", "broccoli",
    "chicken", "beef", "fish", "egg", "cheese", "milk", "butter",
    "bread", "rice", "pasta", "flour", "sugar", "salt", "pepper",
    "oil", "lettuce", "cucumber", "bell pepper", "mushroom",
    "lemon", "lime", "apple", "banana", "orange", "strawberry",
    "spinach", "kale", "avocado", "ginger", "basil", "parsley"
]

# ========== CUSTOM CSS ==========
def load_css():
    st.markdown("""
    <style>
    /* Main container */
    .main {
        padding: 2rem;
    }
    
    /* Recipe cards */
    .recipe-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* Stats boxes */
    .stat-box {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
        border-left: 4px solid #667eea;
    }
    
    /* Button styling */
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        font-weight: 600;
    }
    
    /* Ingredient tags */
    .ingredient-tag {
        display: inline-block;
        background: #e7f3ff;
        padding: 0.3rem 0.8rem;
        border-radius: 15px;
        margin: 0.2rem;
        font-size: 0.9rem;
    }
    
    /* Error/Success messages */
    .success-msg {
        background: #d4edda;
        color: #155724;
        padding: 1rem;
        border-radius: 5px;
        border-left: 4px solid #28a745;
    }
    
    .error-msg {
        background: #f8d7da;
        color: #721c24;
        padding: 1rem;
        border-radius: 5px;
        border-left: 4px solid #dc3545;
    }
    
    /* Loading spinner */
    .stSpinner > div {
        border-color: #667eea !important;
    }
    
    /* Mobile responsive */
    @media (max-width: 768px) {
        .main {
            padding: 1rem;
        }
        .recipe-card {
            padding: 1rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# ========== DATABASE FUNCTIONS ==========
def init_db():
    """Initialize SQLite database with all required tables"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Favorites table
        c.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                recipe_id TEXT PRIMARY KEY,
                added_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Ratings table
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                recipe_id TEXT PRIMARY KEY,
                rating INTEGER CHECK(rating >= 0 AND rating <= 5),
                rated_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # User preferences table
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY,
                dietary_preference TEXT,
                max_cook_time INTEGER,
                difficulty_preference TEXT,
                updated_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Search history table
        c.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredients TEXT,
                search_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Database initialization error: {str(e)}")
        return False

# ========== DATA LOADING ==========
@st.cache_data(show_spinner=False)
def load_recipes() -> List[Dict[str, Any]]:
    """Load recipes from JSON file with error handling"""
    try:
        if not DATA_PATH.exists():
            st.error(f"Recipe file not found at {DATA_PATH}")
            return []
        
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            recipes = json.load(f)
            
        # Validate recipe structure
        validated_recipes = []
        for recipe in recipes:
            if all(key in recipe for key in ['id', 'title', 'ingredients', 'steps']):
                validated_recipes.append(recipe)
        
        return validated_recipes
    except json.JSONDecodeError as e:
        st.error(f"Error parsing recipes.json: {str(e)}")
        return []
    except Exception as e:
        st.error(f"Error loading recipes: {str(e)}")
        return []

# ========== IMAGE RECOGNITION ==========
def recognize_ingredients_from_image(image: Image.Image) -> List[str]:
    """
    Simple ingredient recognition from images.
    In production, this would use a proper ML model (Google Vision API, Azure Computer Vision, etc.)
    For now, we'll simulate with a user-assisted approach.
    """
    try:
        # Convert image to base64 for display
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        st.image(image, caption="Uploaded Image", use_column_width=True)
        
        # In a production app, you would call an ML API here:
        # - Google Cloud Vision API
        # - Azure Computer Vision
        # - AWS Rekognition
        # - Clarifai Food Model
        
        st.info("""
        **Image Recognition Active** 🔍
        
        In production, this would use AI/ML to automatically detect ingredients.
        For now, please select the ingredients you see in the image below.
        """)
        
        # Let user select what they see
        detected = st.multiselect(
            "Select ingredients visible in the image:",
            options=COMMON_INGREDIENTS,
            help="Check all ingredients you can identify in the uploaded image"
        )
        
        return detected
    except Exception as e:
        st.error(f"Error processing image: {str(e)}")
        return []

# ========== INGREDIENT SCALING ==========
def _parse_number_prefix(s: str) -> Tuple[Optional[float], str]:
    """Extract leading numeric quantity (supports fractions, decimals, mixed numbers)"""
    try:
        s = s.strip()
        
        # Mixed number: 1 1/2
        m = re.match(r"^(\d+)\s+(\d+/\d+)\b(.*)$", s)
        if m:
            whole = int(m.group(1))
            frac = Fraction(m.group(2))
            rest = m.group(3).strip()
            return float(whole + frac), rest
        
        # Simple fraction: 1/2
        m = re.match(r"^(\d+/\d+)\b(.*)$", s)
        if m:
            frac = Fraction(m.group(1))
            rest = m.group(2).strip()
            return float(frac), rest
        
        # Decimal or integer
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", s)
        if m:
            num = float(m.group(1))
            rest = m.group(2).strip()
            return num, rest
        
        return None, s
    except Exception:
        return None, s

def scale_ingredients(ingredients: List[str], original_servings: int, new_servings: int) -> List[str]:
    """Scale ingredient quantities based on serving size"""
    try:
        orig = max(1, int(original_servings))
        new = max(1, int(new_servings))
        ratio = new / orig
        
        scaled = []
        for ing in ingredients:
            num, rest = _parse_number_prefix(ing)
            
            if num is None:
                # No quantity found
                if ratio != 1:
                    scaled.append(f"{ing} (×{ratio:.1f})")
                else:
                    scaled.append(ing)
            else:
                # Scale the quantity
                scaled_num = num * ratio
                
                # Smart formatting
                if scaled_num < 0.1:
                    scaled.append(f"{scaled_num:.2f} {rest}".strip())
                elif scaled_num < 1:
                    scaled.append(f"{scaled_num:.2f} {rest}".strip())
                elif scaled_num == int(scaled_num):
                    scaled.append(f"{int(scaled_num)} {rest}".strip())
                else:
                    scaled.append(f"{scaled_num:.1f} {rest}".strip())
        
        return scaled
    except Exception as e:
        st.warning(f"Error scaling ingredients: {str(e)}")
        return ingredients

# ========== SUBSTITUTION SUGGESTIONS ==========
def suggest_substitutions(ingredient: str) -> List[str]:
    """Suggest ingredient substitutions"""
    try:
        ingredient_lower = ingredient.lower().strip()
        
        # Direct match
        if ingredient_lower in SUBSTITUTIONS:
            return SUBSTITUTIONS[ingredient_lower]
        
        # Fuzzy match
        close = get_close_matches(ingredient_lower, SUBSTITUTIONS.keys(), n=1, cutoff=0.6)
        if close:
            return SUBSTITUTIONS[close[0]]
        
        return []
    except Exception:
        return []

# ========== RECIPE MATCHING ==========
def match_recipes(
    available_ingredients: List[str],
    recipes: List[Dict],
    dietary: Optional[str] = None,
    difficulty: Optional[str] = None,
    max_time: Optional[int] = None,
    cuisine: Optional[str] = None,
    max_results: int = 12
) -> List[Dict]:
    """
    Advanced recipe matching algorithm with scoring
    """
    try:
        # Normalize available ingredients
        available = set(i.strip().lower() for i in available_ingredients if i.strip())
        
        if not available:
            return []
        
        results = []
        
        for recipe in recipes:
            try:
                # Get recipe ingredients
                req = set(ing.lower() for ing in recipe.get("ingredients", []))
                
                # Apply filters
                # Dietary filter (strict for vegetarian/vegan)
                if dietary in ("vegetarian", "vegan"):
                    recipe_ings = " ".join(recipe.get("ingredients", [])).lower()
                    if any(non_veg in recipe_ings for non_veg in NON_VEG_INGREDIENTS):
                        continue
                
                if dietary and dietary not in [d.lower() for d in recipe.get("dietary", [])]:
                    continue
                
                # Difficulty filter
                if difficulty and recipe.get("difficulty", "").lower() != difficulty:
                    continue
                
                # Time filter
                if max_time and recipe.get("time_minutes", 0) > max_time:
                    continue
                
                # Cuisine filter
                if cuisine and cuisine.lower() != "any":
                    if recipe.get("cuisine", "").lower() != cuisine.lower():
                        continue
                
                # Calculate match score
                matched_ingredients = []
                for avail_ing in available:
                    for req_ing in req:
                        if avail_ing in req_ing or req_ing in avail_ing:
                            matched_ingredients.append(req_ing)
                            break
                
                matched_ingredients = list(set(matched_ingredients))
                
                if not matched_ingredients:
                    continue
                
                # Scoring algorithm
                match_count = len(matched_ingredients)
                total_required = len(req)
                match_ratio = match_count / max(1, total_required)
                
                # Bonus for exact matches
                exact_matches = len(available & req)
                
                # Calculate final score
                score = (match_count * 2) + (match_ratio * 10) + (exact_matches * 3)
                
                # Bonus for shorter recipes (easier to make)
                if total_required <= 5:
                    score += 2
                
                results.append({
                    'recipe': recipe,
                    'score': score,
                    'match_count': match_count,
                    'total_required': total_required,
                    'match_ratio': match_ratio,
                    'matched_ingredients': matched_ingredients
                })
                
            except Exception as e:
                st.warning(f"Error processing recipe {recipe.get('title', 'Unknown')}: {str(e)}")
                continue
        
        # Sort by score and deduplicate
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # Deduplicate by normalized title
        seen_titles = set()
        unique_results = []
        
        for item in results:
            recipe = item['recipe']
            norm_title = re.sub(r"\(.*?\)", "", recipe["title"].lower()).strip()
            
            if norm_title not in seen_titles:
                seen_titles.add(norm_title)
                unique_results.append(recipe)
                
                if len(unique_results) >= max_results:
                    break
        
        return unique_results
        
    except Exception as e:
        st.error(f"Error matching recipes: {str(e)}")
        return []

# ========== DATABASE OPERATIONS ==========
def add_favorite(recipe_id: str) -> bool:
    """Add recipe to favorites"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO favorites (recipe_id) VALUES (?)", (recipe_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error adding favorite: {str(e)}")
        return False

def remove_favorite(recipe_id: str) -> bool:
    """Remove recipe from favorites"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM favorites WHERE recipe_id=?", (recipe_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error removing favorite: {str(e)}")
        return False

def set_rating(recipe_id: str, rating: int) -> bool:
    """Set recipe rating"""
    try:
        if not (0 <= rating <= 5):
            return False
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO ratings (recipe_id, rating) VALUES (?,?)",
            (recipe_id, rating)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error setting rating: {str(e)}")
        return False

def get_user_ratings() -> Dict[str, int]:
    """Get all user ratings"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT recipe_id, rating FROM ratings")
        res = {row[0]: row[1] for row in c.fetchall()}
        conn.close()
        return res
    except Exception:
        return {}

def get_favorites() -> List[str]:
    """Get all favorite recipe IDs"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT recipe_id FROM favorites ORDER BY added_ts DESC")
        res = [row[0] for row in c.fetchall()]
        conn.close()
        return res
    except Exception:
        return []

def save_search_history(ingredients: List[str]) -> bool:
    """Save search to history"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO search_history (ingredients) VALUES (?)",
            (",".join(ingredients),)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

# ========== RECOMMENDATION ENGINE ==========
def recommend_from_ratings(recipes: List[Dict], user_ratings: Dict[str, int], top_n: int = 6) -> List[Dict]:
    """Generate personalized recommendations based on user ratings"""
    try:
        # Get highly rated recipes (4-5 stars)
        liked = [rid for rid, r in user_ratings.items() if r >= 4]
        
        if not liked:
            # Return popular recipes if no ratings
            return recipes[:top_n]
        
        # Analyze preferences
        liked_recipes = [r for r in recipes if r["id"] in liked]
        
        # Count cuisines and dietary preferences
        cuisine_counts = {}
        dietary_counts = {}
        difficulty_counts = {}
        
        for recipe in liked_recipes:
            # Cuisine
            cuisine = recipe.get("cuisine", "unknown")
            cuisine_counts[cuisine] = cuisine_counts.get(cuisine, 0) + 1
            
            # Dietary
            for diet in recipe.get("dietary", []):
                dietary_counts[diet] = dietary_counts.get(diet, 0) + 1
            
            # Difficulty
            diff = recipe.get("difficulty", "medium")
            difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
        
        # Score recipes based on similarity
        scored_recipes = []
        for recipe in recipes:
            if recipe["id"] in liked:
                continue  # Skip already rated
            
            score = 0
            
            # Cuisine match
            cuisine = recipe.get("cuisine", "unknown")
            score += cuisine_counts.get(cuisine, 0) * 3
            
            # Dietary match
            for diet in recipe.get("dietary", []):
                score += dietary_counts.get(diet, 0) * 2
            
            # Difficulty match
            diff = recipe.get("difficulty", "medium")
            score += difficulty_counts.get(diff, 0)
            
            if score > 0:
                scored_recipes.append((score, recipe))
        
        # Sort and return top N
        scored_recipes.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in scored_recipes[:top_n]]
        
    except Exception as e:
        st.warning(f"Error generating recommendations: {str(e)}")
        return recipes[:top_n]

# ========== UI COMPONENTS ==========
def display_recipe_card(recipe: Dict, servings: int = 1):
    """Display a single recipe in an expandable card"""
    try:
        # Get original servings
        orig_servings = recipe.get('servings', 1) or 1
        try:
            orig_servings = int(orig_servings)
        except:
            orig_servings = 1
        
        # Recipe header
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            st.markdown(f"### {recipe['title']}")
        
        with col2:
            st.metric("⏱️ Time", f"{recipe.get('time_minutes', '?')} min")
        
        with col3:
            st.metric("👨‍🍳 Level", recipe.get('difficulty', '?').title())
        
        # Recipe details
        st.markdown(f"**Cuisine:** {recipe.get('cuisine', 'N/A')} • **Dietary:** {', '.join(recipe.get('dietary', ['None']))}")
        
        # Ingredients section
        st.markdown("#### 📝 Ingredients")
        st.caption(f"Original: {orig_servings} serving(s) → Scaled to: {servings} serving(s)")
        
        scaled_ingredients = scale_ingredients(
            recipe.get('ingredients', []),
            orig_servings,
            servings
        )
        
        for ing in scaled_ingredients:
            # Extract first word for substitution check
            first_word = re.split(r'[\s,()]', ing)[0].lower()
            subs = suggest_substitutions(first_word)
            
            if subs:
                st.markdown(f"- {ing}")
                st.caption(f"   💡 Substitutes: {', '.join(subs)}")
            else:
                st.markdown(f"- {ing}")
        
        # Instructions section
        st.markdown("#### 👩‍🍳 Instructions")
        for idx, step in enumerate(recipe.get('steps', []), 1):
            st.markdown(f"**Step {idx}:** {step}")
        
        # Nutrition section
        if recipe.get('nutrition'):
            st.markdown("#### 🥗 Nutrition Information")
            nutrition = recipe.get('nutrition', {})
            
            cols = st.columns(len(nutrition))
            for col, (key, value) in zip(cols, nutrition.items()):
                with col:
                    st.metric(key.title(), value)
        
        # Action buttons
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("❤️ Save Favorite", key=f"fav_{recipe['id']}", use_container_width=True):
                if add_favorite(recipe['id']):
                    st.success("✅ Added to favorites!")
                    st.rerun()
        
        with col2:
            current_ratings = get_user_ratings()
            current_rating = current_ratings.get(recipe['id'], 0)
            
            rating = st.selectbox(
                "⭐ Rate",
                options=[0, 1, 2, 3, 4, 5],
                index=current_rating,
                key=f"rate_select_{recipe['id']}"
            )
            
            if st.button("Submit", key=f"rate_btn_{recipe['id']}", use_container_width=True):
                if set_rating(recipe['id'], rating):
                    st.success(f"✅ Rated {rating} stars!")
                    st.rerun()
        
        with col3:
            if st.button("🗑️ Remove Favorite", key=f"unfav_{recipe['id']}", use_container_width=True):
                if remove_favorite(recipe['id']):
                    st.info("Removed from favorites")
                    st.rerun()
        
    except Exception as e:
        st.error(f"Error displaying recipe: {str(e)}")

# ========== MAIN APP ==========
def main():
    """Main application logic"""
    try:
        # Initialize
        load_css()
        
        if not init_db():
            st.error("Failed to initialize database. Please check file permissions.")
            return
        
        # Load recipes
        with st.spinner("Loading recipes..."):
            recipes = load_recipes()
        
        if not recipes:
            st.error("No recipes loaded. Please ensure recipes.json exists and is valid.")
            return
        
        # Header
        st.title("🍽️ Smart Recipe Generator")
        st.markdown("### Discover recipes based on your available ingredients")
        
        # Get unique cuisines
        cuisines = sorted(list(set(r.get("cuisine", "Unknown") for r in recipes)))
        
        # Sidebar
        with st.sidebar:
            st.header("🎛️ Filters & Settings")
            
            # User preferences
            dietary_pref = st.selectbox(
                "Dietary Preference",
                ["Any", "Vegetarian", "Vegan", "Gluten-Free"],
                help="Filter recipes by dietary requirements"
            )
            
            difficulty_pref = st.selectbox(
                "Difficulty Level",
                ["Any", "Easy", "Medium", "Hard"],
                help="Filter by cooking difficulty"
            )
            
            max_time = st.slider(
                "Max Cooking Time (minutes)",
                min_value=5,
                max_value=240,
                value=60,
                step=5,
                help="Maximum time you want to spend cooking"
            )
            
            cuisine_pref = st.selectbox(
                "Cuisine Type",
                ["Any"] + cuisines,
                help="Filter by cuisine type"
            )
            
            max_results = st.slider(
                "Maximum Results",
                min_value=3,
                max_value=20,
                value=8,
                help="Number of recipes to show"
            )
            
            st.markdown("---")
            
            # Favorites section
            st.header("⭐ Your Favorites")
            favs = get_favorites()
            
            if favs:
                recipes_map = {r['id']: r for r in recipes}
                for fid in favs[:5]:  # Show only top 5
                    if fid in recipes_map:
                        r = recipes_map[fid]
                        st.markdown(f"- **{r['title']}**")
                        st.caption(f"   {r.get('time_minutes', '?')} min • {r.get('difficulty', '?')}")
                
                if len(favs) > 5:
                    st.caption(f"...and {len(favs) - 5} more")
            else:
                st.info("No favorites yet. Start adding recipes!")
            
            st.markdown("---")
            
            # Recommendations
            st.header("🎯 Recommended for You")
            user_ratings = get_user_ratings()
            recommendations = recommend_from_ratings(recipes, user_ratings, top_n=5)
            
            if recommendations:
                for rec in recommendations:
                    st.markdown(f"- **{rec['title']}**")
                    st.caption(f"   {rec.get('cuisine', 'N/A')} • {rec.get('time_minutes', '?')} min")
            else:
                st.caption("Rate some recipes to get personalized suggestions!")
        
        # Main content
        tab1, tab2, tab3 = st.tabs(["🔍 Search Recipes", "📸 Image Recognition", "📊 Statistics"])
        
        with tab1:
            # Search form
            with st.form("search_form", clear_on_submit=False):
                st.subheader("Enter Your Ingredients")
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    ing_text = st.text_input(
                        "Type ingredients (comma-separated)",
                        placeholder="e.g., tomato, onion, garlic, chicken",
                        help="Enter ingredients you have available"
                    )
                
                with col2:
                    servings = st.number_input(
                        "Number of Servings",
                        min_value=1,
                        max_value=20,
                        value=2,
                        step=1,
                        help="Recipes will be scaled to this serving size"
                    )
                
                # Common ingredients multiselect
                common_ings = sorted(list(set(
                    ing.lower()
                    for r in recipes
                    for ing in r.get("ingredients", [])
                )))[:100]
                
                selected_ings = st.multiselect(
                    "Or select from common ingredients",
                    options=common_ings,
                    help="Quick select from frequently used ingredients"
                )
                
                submitted = st.form_submit_button("🔍 Find Recipes", use_container_width=True)
            
            # Process search
            if submitted:
                # Combine text and selected ingredients
                text_ings = [i.strip() for i in ing_text.split(",") if i.strip()]
                all_ingredients = list(set(text_ings + selected_ings))
                
                if not all_ingredients:
                    st.warning("⚠️ Please enter at least one ingredient.")
                else:
                    # Save search
                    save_search_history(all_ingredients)
                    
                    # Show what we're searching for
                    st.info(f"🔎 Searching with ingredients: {', '.join(all_ingredients)}")
                    
                    # Apply filters
                    dietary_filter = None if dietary_pref == "Any" else dietary_pref.lower()
                    difficulty_filter = None if difficulty_pref == "Any" else difficulty_pref.lower()
                    cuisine_filter = None if cuisine_pref == "Any" else cuisine_pref
                    
                    # Search
                    with st.spinner("🔮 Finding perfect recipes for you..."):
                        matches = match_recipes(
                            all_ingredients,
                            recipes,
                            dietary=dietary_filter,
                            difficulty=difficulty_filter,
                            max_time=max_time,
                            cuisine=cuisine_filter,
                            max_results=max_results
                        )
                    
                    # Display results
                    if not matches:
                        st.warning("😔 No recipes found matching your criteria.")
                        st.info("💡 Try:\n- Adding more ingredients\n- Removing some filters\n- Adjusting the cooking time")
                    else:
                        st.success(f"✨ Found {len(matches)} delicious recipe(s) for {servings} serving(s)!")
                        
                        # Display recipes
                        for idx, recipe in enumerate(matches, 1):
                            with st.expander(
                                f"🍴 {idx}. {recipe['title']} ({recipe.get('time_minutes', '?')} min)",
                                expanded=(idx == 1)  # First recipe expanded
                            ):
                                display_recipe_card(recipe, servings)
        
        with tab2:
            st.subheader("📸 Ingredient Recognition from Image")
            st.markdown("Upload a photo of your ingredients to automatically detect them!")
            
            uploaded_file = st.file_uploader(
                "Choose an image",
                type=['png', 'jpg', 'jpeg'],
                help="Upload a clear photo of your ingredients"
            )
            
            if uploaded_file is not None:
                try:
                    # Load image
                    image = Image.open(uploaded_file)
                    
                    # Display and recognize
                    detected_ingredients = recognize_ingredients_from_image(image)
                    
                    if detected_ingredients:
                        st.success(f"✅ Detected {len(detected_ingredients)} ingredients!")
                        
                        # Display as tags
                        st.markdown("**Detected Ingredients:**")
                        cols = st.columns(4)
                        for idx, ing in enumerate(detected_ingredients):
                            with cols[idx % 4]:
                                st.markdown(f'<div class="ingredient-tag">{ing}</div>', unsafe_allow_html=True)
                        
                        st.markdown("---")
                        
                        # Servings input
                        img_servings = st.number_input(
                            "Servings for these ingredients",
                            min_value=1,
                            max_value=20,
                            value=2,
                            key="img_servings"
                        )
                        
                        # Search button
                        if st.button("🔍 Find Recipes with These Ingredients", use_container_width=True):
                            dietary_filter = None if dietary_pref == "Any" else dietary_pref.lower()
                            difficulty_filter = None if difficulty_pref == "Any" else difficulty_pref.lower()
                            cuisine_filter = None if cuisine_pref == "Any" else cuisine_pref
                            
                            with st.spinner("Finding recipes..."):
                                matches = match_recipes(
                                    detected_ingredients,
                                    recipes,
                                    dietary=dietary_filter,
                                    difficulty=difficulty_filter,
                                    max_time=max_time,
                                    cuisine=cuisine_filter,
                                    max_results=max_results
                                )
                            
                            if matches:
                                st.success(f"Found {len(matches)} recipes!")
                                
                                for idx, recipe in enumerate(matches, 1):
                                    with st.expander(
                                        f"🍴 {idx}. {recipe['title']}",
                                        expanded=(idx == 1)
                                    ):
                                        display_recipe_card(recipe, img_servings)
                            else:
                                st.warning("No recipes found. Try adjusting filters.")
                    
                except Exception as e:
                    st.error(f"❌ Error processing image: {str(e)}")
            else:
                st.info("👆 Upload an image to get started")
                
                # Show example
                st.markdown("""
                **How it works:**
                1. Take a clear photo of your ingredients
                2. Upload it using the button above
                3. Select the ingredients you see
                4. Get instant recipe suggestions!
                
                **Tips for best results:**
                - Use good lighting
                - Arrange ingredients clearly
                - Avoid cluttered backgrounds
                """)
        
        with tab3:
            st.subheader("📊 Your Recipe Statistics")
            
            # Calculate stats
            total_recipes = len(recipes)
            total_favorites = len(get_favorites())
            total_ratings = len(get_user_ratings())
            
            # Display stats
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown('<div class="stat-box">', unsafe_allow_html=True)
                st.metric("Total Recipes", total_recipes)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="stat-box">', unsafe_allow_html=True)
                st.metric("Your Favorites", total_favorites)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col3:
                st.markdown('<div class="stat-box">', unsafe_allow_html=True)
                st.metric("Recipes Rated", total_ratings)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col4:
                avg_rating = 0
                if total_ratings > 0:
                    ratings = get_user_ratings()
                    avg_rating = sum(ratings.values()) / len(ratings)
                
                st.markdown('<div class="stat-box">', unsafe_allow_html=True)
                st.metric("Avg Rating", f"{avg_rating:.1f} ⭐")
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Cuisine breakdown
            st.subheader("🌍 Recipes by Cuisine")
            cuisine_counts = {}
            for r in recipes:
                cuisine = r.get("cuisine", "Unknown")
                cuisine_counts[cuisine] = cuisine_counts.get(cuisine, 0) + 1
            
            if cuisine_counts:
                sorted_cuisines = sorted(cuisine_counts.items(), key=lambda x: x[1], reverse=True)
                
                for cuisine, count in sorted_cuisines[:10]:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{cuisine}**")
                    with col2:
                        st.write(f"{count} recipes")
                    st.progress(count / total_recipes)
            
            st.markdown("---")
            
            # Difficulty breakdown
            st.subheader("📈 Difficulty Distribution")
            difficulty_counts = {}
            for r in recipes:
                diff = r.get("difficulty", "Unknown").title()
                difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
            
            cols = st.columns(len(difficulty_counts))
            for col, (diff, count) in zip(cols, difficulty_counts.items()):
                with col:
                    st.metric(diff, count)
            
            st.markdown("---")
            
            # Your top rated recipes
            st.subheader("⭐ Your Top Rated Recipes")
            user_ratings = get_user_ratings()
            
            if user_ratings:
                top_rated = sorted(user_ratings.items(), key=lambda x: x[1], reverse=True)[:5]
                recipes_map = {r['id']: r for r in recipes}
                
                for recipe_id, rating in top_rated:
                    if recipe_id in recipes_map:
                        r = recipes_map[recipe_id]
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**{r['title']}**")
                            st.caption(f"{r.get('cuisine', 'N/A')} • {r.get('time_minutes', '?')} min")
                        with col2:
                            st.write("⭐" * rating)
            else:
                st.info("Start rating recipes to see your favorites here!")
        
        # Footer
        st.markdown("---")
        st.markdown("""
        <div style='text-align: center; color: #666; padding: 20px;'>
            <p>🍽️ <strong>Smart Recipe Generator</strong></p>
            <p>Built with Streamlit • Made with ❤️ for food lovers</p>
            <p style='font-size: 0.8rem;'>
                Total Recipes: {total} | Database: SQLite | 
                Features: Image Recognition, Smart Matching, Personalized Recommendations
            </p>
        </div>
        """.format(total=len(recipes)), unsafe_allow_html=True)
        
    except Exception as e:
        st.error(f"❌ Application error: {str(e)}")
        st.error("Please refresh the page or contact support if the issue persists.")

if __name__ == "__main__":
    main()
