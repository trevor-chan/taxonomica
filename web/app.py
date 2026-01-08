#!/usr/bin/env python3
"""Taxonomica Web - A taxonomy guessing game web interface.

Run with:
    python web/app.py

Then visit http://localhost:8080
"""

import hashlib
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request, jsonify, session

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.gbif_backbone import GBIFBackbone
from taxonomica.gbif_tree import GBIFTaxonomyTree, TaxonomyNode
from taxonomica.wikipedia import WikipediaData
from taxonomica.redaction import Redactor, build_redaction_terms_from_node
from taxonomica.popularity import PopularityIndex

app = Flask(__name__)
app.secret_key = 'taxonomica-secret-key-change-in-production'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # Set True in production with HTTPS

# Global data (loaded once at startup)
tree: GBIFTaxonomyTree | None = None
wiki: WikipediaData | None = None
popularity_index: PopularityIndex | None = None

# Server-side cache for game descriptions (to avoid cookie size limits)
# In production, use Redis or similar. This is fine for single-server development.
game_descriptions: dict[str, list[str]] = {}

# Difficulty thresholds
DIFFICULTY_THRESHOLDS = {
    "easy": 55,
    "medium": 49,
    "hard": 24,
    "expert": 0,
}

# Game ranks
ALL_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]

# Rank titles data
rank_titles_data: dict | None = None


def load_rank_titles() -> dict:
    """Load rank titles from JSON file."""
    global rank_titles_data
    if rank_titles_data is not None:
        return rank_titles_data
    
    titles_path = Path(__file__).parent.parent / "examples" / "rank_titles.json"
    if titles_path.exists():
        with open(titles_path) as f:
            rank_titles_data = json.load(f)
            return rank_titles_data
    return {}


def get_rank_title(score: int, target_node: TaxonomyNode) -> str | None:
    """Get a rank title based on score and the target species' taxonomy."""
    titles_data = load_rank_titles()
    if not titles_data or "titles" not in titles_data:
        return None
    
    # Determine tier based on score
    if score == 0:
        tier_name = "perfect"
    elif score <= 7:
        tier_name = "excellent"
    elif score <= 14:
        tier_name = "good"
    else:
        tier_name = "needs_improvement"
    
    # Extract taxonomy info from the target's path
    player_taxa = {"generic"}
    node = target_node
    while node and node.parent:
        if node.name:
            player_taxa.add(node.name)
        node = node.parent
    
    # Find matching titles
    specific_matches = []
    generic_matches = []
    
    for title, info in titles_data["titles"].items():
        if tier_name not in info.get("tiers", []):
            continue
        
        title_taxa = set(info.get("taxa", []))
        matching_taxa = title_taxa & player_taxa
        
        if matching_taxa:
            if matching_taxa == {"generic"}:
                generic_matches.append(title)
            else:
                specific_matches.append(title)
    
    # Prefer specific matches over generic
    if specific_matches:
        return random.choice(specific_matches)
    elif generic_matches:
        return random.choice(generic_matches)
    
    return None


def get_seed_from_string(seed_string: str) -> int:
    """Convert a seed string to an integer seed."""
    hash_bytes = hashlib.sha256(seed_string.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder='big')


def split_into_lines(text: str, line_width: int = 90) -> list[str]:
    """Split text into wrapped lines."""
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        word_len = len(word)
        if current_length + word_len + (1 if current_line else 0) > line_width:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = word_len
        else:
            current_line.append(word)
            current_length += word_len + (1 if len(current_line) > 1 else 0)
    
    if current_line:
        lines.append(" ".join(current_line))
    
    return lines


def find_species_with_wikipedia(
    difficulty: str = "expert",
    seed: int | None = None,
    max_attempts: int = 200,
) -> tuple[TaxonomyNode, str] | None:
    """Find a species that has a Wikipedia entry with description."""
    global tree, wiki, popularity_index
    
    min_score = DIFFICULTY_THRESHOLDS.get(difficulty, 0)
    
    # Pre-filter by difficulty
    candidate_names: set[str] | None = None
    if difficulty != "expert" and popularity_index and min_score > 0:
        candidate_names = set()
        for metrics in popularity_index._by_id.values():
            if metrics.popularity_score >= min_score and metrics.section_count >= 2:
                candidate_names.add(metrics.scientific_name.lower())
    
    # Get species nodes
    species_nodes = []
    for node in tree._nodes_by_id.values():
        if node.rank == "species" and node.has_complete_path():
            if candidate_names is not None:
                if node.name.lower() not in candidate_names:
                    continue
            species_nodes.append(node)
    
    if not species_nodes:
        return None
    
    # Sort for deterministic ordering
    species_nodes.sort(key=lambda n: n.id)
    
    # Create seeded random generator
    rng = random.Random(seed) if seed is not None else random.Random()
    rng.shuffle(species_nodes)
    
    # Find species with Wikipedia entry
    for node in species_nodes[:max_attempts]:
        wiki_species = wiki.match_gbif_taxon(node.name)
        if wiki_species:
            full_text = wiki_species.get_useful_text()
            if full_text and len(full_text) > 400:
                lines = split_into_lines(full_text)
                if len(lines) >= 12:
                    return node, full_text
    
    return None


def get_correct_path(node: TaxonomyNode) -> list[dict]:
    """Get the correct path from root to this node."""
    path = []
    current = node
    while current:
        path.append({
            'id': current.id,
            'name': current.name,
            'rank': current.rank,
            'vernacular': current.vernacular_names[0] if current.vernacular_names else None,
        })
        current = current.parent
    path.reverse()
    return path


def get_choices_at_node(node_id: str, target_rank: str) -> list[dict]:
    """Get available choices at a node for a target rank."""
    global tree
    
    node = tree._nodes_by_id.get(node_id)
    if not node:
        return []
    
    choices = []
    for child in node.children.values():
        if child.rank == target_rank and child.has_complete_path():
            # For non-species levels, exclude leaf nodes
            if target_rank != "species" and not child.children:
                continue
            choices.append({
                'id': child.id,
                'name': child.name,
                'rank': child.rank,
                'vernacular': child.vernacular_names[0] if child.vernacular_names else None,
                'descendants': child.count_descendants(),
            })
    
    # Sort by descendants (descending), then alphabetically
    choices.sort(key=lambda c: (-c['descendants'], c['name'].lower()))
    return choices


def get_node_info(node_id: str) -> dict | None:
    """Get detailed info about a node."""
    global tree, wiki
    
    node = tree._nodes_by_id.get(node_id)
    if not node:
        return None
    
    info = {
        'id': node.id,
        'name': node.name,
        'rank': node.rank,
        'vernacular': node.vernacular_names[0] if node.vernacular_names else None,
        'descendants': node.count_descendants(),
        'description': None,
    }
    
    # Try to get Wikipedia description
    wiki_entry = wiki.match_gbif_taxon(node.name)
    if wiki_entry:
        desc = wiki_entry.get_useful_text() or wiki_entry.get_abstract()
        if desc:
            info['description'] = desc[:3000]
    
    return info


@app.route('/')
def index():
    """Main game page."""
    return render_template('index.html')


@app.route('/health')
def health():
    """Health check endpoint for debugging."""
    return jsonify({
        'status': 'ok',
        'tree_loaded': tree is not None,
        'wiki_loaded': wiki is not None,
        'popularity_loaded': popularity_index is not None,
    })


@app.route('/api/start', methods=['POST'])
def start_game():
    """Start a new game."""
    global tree
    
    data = request.json or {}
    difficulty = data.get('difficulty', 'medium')
    seed_string = data.get('seed', '')
    round_number = data.get('round', 1)
    
    # Calculate seed
    if seed_string:
        base_seed = get_seed_from_string(seed_string)
        seed = base_seed + round_number
    else:
        seed = None
    
    # Find a species
    result = find_species_with_wikipedia(difficulty, seed)
    if not result:
        return jsonify({'error': 'Could not find a species'}), 500
    
    target_node, description = result
    
    # Get correct path
    correct_path = get_correct_path(target_node)
    
    # Build redaction terms
    terms = build_redaction_terms_from_node(target_node)
    redactor = Redactor(terms)
    
    # Split into lines for progressive reveal
    lines = split_into_lines(description)
    
    # Clean up old game description if exists
    old_game = session.get('game')
    if old_game and 'game_id' in old_game:
        old_game_id = old_game['game_id']
        if old_game_id in game_descriptions:
            del game_descriptions[old_game_id]
    
    # Generate a game ID for server-side storage
    import uuid
    game_id = str(uuid.uuid4())
    
    # Store description lines in server-side cache (not in cookie)
    game_descriptions[game_id] = lines
    
    # Store game state in session (minimal data only)
    session['game'] = {
        'game_id': game_id,  # Reference to server-side cached description
        'target_id': target_node.id,
        'target_name': target_node.name,
        'target_vernacular': target_node.vernacular_names[0] if target_node.vernacular_names else None,
        'correct_path': correct_path,
        # 'description_lines' moved to server-side cache
        'total_lines': len(lines),
        'difficulty': difficulty,
        'seed_string': seed_string,
        'round_number': round_number,
        'current_node_id': tree.root.id,
        'current_rank_index': 0,
        'score': 0,
        'guesses': 0,
        'level_wrong_guesses': 0,
        'visible_lines': 3,
        'revealed_path': [],
    }
    
    # Get initial choices
    choices = get_choices_at_node(tree.root.id, ALL_RANKS[0])
    
    # Redact visible description
    visible_text = "\n".join(lines[:3])
    redacted_text = redactor.redact(visible_text)
    
    return jsonify({
        'success': True,
        'current_rank': ALL_RANKS[0],
        'choices': choices,
        'description': redacted_text,
        'visible_lines': 3,
        'total_lines': len(lines),
        'score': 0,
        'progress': f"0/{len(ALL_RANKS)}",
        'difficulty': difficulty,
        'seed_string': seed_string,
        'round_number': round_number,
        'guesses_left': 5,
    })


def get_description_lines(game: dict) -> list[str]:
    """Get description lines from server-side cache."""
    game_id = game.get('game_id')
    if game_id and game_id in game_descriptions:
        return game_descriptions[game_id]
    return []


@app.route('/api/guess', methods=['POST'])
def make_guess():
    """Make a guess."""
    global tree
    
    data = request.json or {}
    choice_id = data.get('choice_id')
    
    game = session.get('game')
    if not game:
        return jsonify({'error': 'No active game'}), 400
    
    # Get description lines from server-side cache
    description_lines = get_description_lines(game)
    
    # Get target node for redaction
    target_node = tree._nodes_by_id.get(game['target_id'])
    terms = build_redaction_terms_from_node(target_node)
    redactor = Redactor(terms)
    
    # Find the correct answer
    current_rank = ALL_RANKS[game['current_rank_index']]
    correct_path = game['correct_path']
    
    # Find correct node at current rank
    correct_id = None
    for node in correct_path:
        if node['rank'] == current_rank:
            correct_id = node['id']
            break
    
    game['guesses'] += 1
    
    # Check if correct
    is_correct = (choice_id == correct_id)
    
    if is_correct:
        # Advance to next level
        game['current_rank_index'] += 1
        game['level_wrong_guesses'] = 0
        
        # Reveal more lines (for both correct and incorrect answers)
        game['visible_lines'] = min(game['visible_lines'] + 1, len(description_lines))
        
        # Update current node and revealed path
        game['current_node_id'] = choice_id
        chosen_node = tree._nodes_by_id.get(choice_id)
        game['revealed_path'].append({
            'name': chosen_node.name,
            'rank': chosen_node.rank,
            'vernacular': chosen_node.vernacular_names[0] if chosen_node.vernacular_names else None,
        })
        
        # Check if game complete
        if game['current_rank_index'] >= len(ALL_RANKS):
            session['game'] = game
            # Get rank title
            target_node = tree._nodes_by_id.get(game['target_id'])
            rank_title = get_rank_title(game['score'], target_node) if target_node else None
            
            return jsonify({
                'correct': True,
                'complete': True,
                'target_name': game['target_name'],
                'target_vernacular': game['target_vernacular'],
                'score': game['score'],
                'guesses': game['guesses'],
                'correct_path': game['correct_path'],
                'rank_title': rank_title,
            })
        
        # Get next choices
        next_rank = ALL_RANKS[game['current_rank_index']]
        choices = get_choices_at_node(choice_id, next_rank)
        
        session['game'] = game
        
        # Redact description
        visible_text = "\n".join(description_lines[:game['visible_lines']])
        redacted_text = redactor.redact(visible_text)
        
        return jsonify({
            'correct': True,
            'complete': False,
            'current_rank': next_rank,
            'choices': choices,
            'description': redacted_text,
            'visible_lines': game['visible_lines'],
            'total_lines': len(description_lines),
            'score': game['score'],
            'progress': f"{game['current_rank_index']}/{len(ALL_RANKS)}",
            'revealed_path': game['revealed_path'],
            'guesses_left': 5,  # Reset after correct guess
        })
    else:
        # Wrong guess
        game['score'] += 1
        game['level_wrong_guesses'] += 1
        
        # Reveal more lines
        game['visible_lines'] = min(game['visible_lines'] + 1, len(description_lines))
        
        # Check if guess cap reached (5 wrong per level)
        if game['level_wrong_guesses'] >= 5:
            # Apply penalty and auto-advance
            game['score'] += 3
            game['current_rank_index'] += 1
            game['level_wrong_guesses'] = 0
            
            # Find and reveal correct answer
            correct_node = tree._nodes_by_id.get(correct_id)
            game['current_node_id'] = correct_id
            game['revealed_path'].append({
                'name': correct_node.name,
                'rank': correct_node.rank,
                'vernacular': correct_node.vernacular_names[0] if correct_node.vernacular_names else None,
            })
            
            # Check if complete
            if game['current_rank_index'] >= len(ALL_RANKS):
                session['game'] = game
                # Get rank title
                target_node_for_title = tree._nodes_by_id.get(game['target_id'])
                rank_title = get_rank_title(game['score'], target_node_for_title) if target_node_for_title else None
                
                return jsonify({
                    'correct': False,
                    'guess_cap': True,
                    'complete': True,
                    'correct_answer': {
                        'name': correct_node.name,
                        'vernacular': correct_node.vernacular_names[0] if correct_node.vernacular_names else None,
                    },
                    'target_name': game['target_name'],
                    'target_vernacular': game['target_vernacular'],
                    'score': game['score'],
                    'guesses': game['guesses'],
                    'correct_path': game['correct_path'],
                    'rank_title': rank_title,
                })
            
            # Get next choices
            next_rank = ALL_RANKS[game['current_rank_index']]
            choices = get_choices_at_node(correct_id, next_rank)
            
            session['game'] = game
            
            visible_text = "\n".join(description_lines[:game['visible_lines']])
            redacted_text = redactor.redact(visible_text)
            
            return jsonify({
                'correct': False,
                'guess_cap': True,
                'complete': False,
                'correct_answer': {
                    'name': correct_node.name,
                    'vernacular': correct_node.vernacular_names[0] if correct_node.vernacular_names else None,
                },
                'current_rank': next_rank,
                'choices': choices,
                'description': redacted_text,
                'visible_lines': game['visible_lines'],
                'total_lines': len(description_lines),
                'score': game['score'],
                'progress': f"{game['current_rank_index']}/{len(ALL_RANKS)}",
                'revealed_path': game['revealed_path'],
                'guesses_left': 5,
            })
        
        # Regular wrong guess
        guesses_left = 5 - game['level_wrong_guesses']
        
        session['game'] = game
        
        visible_text = "\n".join(description_lines[:game['visible_lines']])
        redacted_text = redactor.redact(visible_text)
        
        # Get current choices again
        choices = get_choices_at_node(game['current_node_id'], current_rank)
        
        return jsonify({
            'correct': False,
            'guess_cap': False,
            'description': redacted_text,
            'visible_lines': game['visible_lines'],
            'total_lines': len(description_lines),
            'score': game['score'],
            'guesses_left': guesses_left,
            'choices': choices,
        })


@app.route('/api/info/<node_id>')
def node_info(node_id: str):
    """Get info about a node."""
    info = get_node_info(node_id)
    if not info:
        return jsonify({'error': 'Node not found'}), 404
    return jsonify(info)


@app.route('/api/current_info')
def current_node_info():
    """Get info about the current node."""
    game = session.get('game')
    if not game:
        return jsonify({'error': 'No active game'}), 400
    
    info = get_node_info(game['current_node_id'])
    if not info:
        return jsonify({'error': 'Node not found'}), 404
    return jsonify(info)


def load_data():
    """Load taxonomy data at startup."""
    global tree, wiki, popularity_index
    
    base_path = Path(__file__).parent.parent
    backbone_path = base_path / "backbone"
    wiki_path = base_path / "wikipedia-en-dwca"
    
    print("Loading GBIF Backbone Taxonomy...")
    backbone = GBIFBackbone(backbone_path)
    tree = GBIFTaxonomyTree.from_backbone(backbone, accepted_only=True)
    
    print("Loading vernacular names...")
    tree.add_vernacular_names(backbone)
    
    print("Loading Wikipedia data...")
    wiki = WikipediaData(wiki_path)
    
    print("Building popularity index...")
    popularity_index = PopularityIndex.from_wikipedia_dwca(wiki_path)
    
    print("Data loaded!")


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("Starting Taxonomica Web Server...")
    print("=" * 50 + "\n")
    
    load_data()
    
    print("\n" + "=" * 50)
    print("Server ready!")
    print("Visit: http://127.0.0.1:8080")
    print("Health check: http://127.0.0.1:8080/health")
    print("=" * 50 + "\n")
    
    app.run(debug=True, port=8080, host='127.0.0.1')

