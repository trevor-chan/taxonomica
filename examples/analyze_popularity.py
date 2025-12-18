#!/usr/bin/env python3
"""Analyze popularity score distributions for Wikipedia species entries.

This script prints detailed statistics about the distribution of:
- Overall popularity scores
- Description length
- Section count
- Vernacular name presence
- Multimedia count

Usage:
    python examples/analyze_popularity.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.popularity import PopularityIndex


def percentile(data: list, p: float) -> float:
    """Calculate percentile without numpy."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def histogram_text(data: list, bins: int = 20, width: int = 50, title: str = "") -> str:
    """Create a text-based histogram."""
    if not data:
        return "No data"
    
    min_val = min(data)
    max_val = max(data)
    if max_val == min_val:
        max_val = min_val + 1
    
    bin_width = (max_val - min_val) / bins
    counts = [0] * bins
    
    for val in data:
        bin_idx = min(int((val - min_val) / bin_width), bins - 1)
        counts[bin_idx] += 1
    
    max_count = max(counts)
    
    lines = [title, "=" * len(title) if title else ""]
    
    for i, count in enumerate(counts):
        bin_start = min_val + i * bin_width
        bin_end = min_val + (i + 1) * bin_width
        bar_len = int(count / max_count * width) if max_count > 0 else 0
        bar = "█" * bar_len
        lines.append(f"  {bin_start:8.1f} - {bin_end:8.1f} | {bar} ({count:,})")
    
    return "\n".join(lines)


def main():
    wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    
    if not wiki_path.exists():
        print(f"ERROR: Wikipedia data not found at {wiki_path}")
        return
    
    print("Building popularity index...")
    index = PopularityIndex.from_wikipedia_dwca(wiki_path)
    
    # Collect metrics
    scores = []
    desc_lengths = []
    section_counts = []
    has_vernacular_count = 0
    multimedia_counts = []
    
    print("Collecting metrics...")
    for metrics in index._by_id.values():
        scores.append(metrics.popularity_score)
        desc_lengths.append(metrics.description_length)
        section_counts.append(metrics.section_count)
        if metrics.has_vernacular:
            has_vernacular_count += 1
        multimedia_counts.append(metrics.multimedia_count)
    
    total = len(scores)
    print(f"Total taxa: {total:,}")
    
    # Current tier distribution
    tier_counts = index.get_stats()
    
    print("\n" + "=" * 70)
    print("DIFFICULTY TIERS (inclusive - each includes easier tiers)")
    print("=" * 70)
    
    # Calculate inclusive counts
    easy_count = tier_counts['easy']
    medium_count = tier_counts['easy'] + tier_counts['medium']
    hard_count = tier_counts['easy'] + tier_counts['medium'] + tier_counts['hard']
    
    print(f"\n  Easy   (score >= 55): {easy_count:,} taxa ({easy_count/total*100:.1f}%) - Top 1%")
    print(f"  Medium (score >= 49): {medium_count:,} taxa ({medium_count/total*100:.1f}%) - Top 5%")
    print(f"  Hard   (score >= 24): {hard_count:,} taxa ({hard_count/total*100:.1f}%) - Top 25%")
    print(f"  Expert (all species): {total:,} taxa (100%)")
    
    print("\n" + "=" * 70)
    print("POPULARITY SCORE DISTRIBUTION")
    print("=" * 70)
    
    print(f"\n  Min: {min(scores):.1f}")
    print(f"  Max: {max(scores):.1f}")
    print(f"  Mean: {sum(scores)/len(scores):.1f}")
    print(f"  Median: {percentile(scores, 50):.1f}")
    
    print("\n  Percentiles:")
    for p in [5, 10, 25, 50, 75, 90, 95, 99]:
        val = percentile(scores, p)
        count_above = sum(1 for s in scores if s >= val)
        print(f"    P{p:2}: {val:5.1f}  ({count_above:,} taxa above this)")
    
    print("\n" + histogram_text(scores, bins=20, title="Score Distribution"))
    
    print("\n" + "=" * 70)
    print("DESCRIPTION LENGTH DISTRIBUTION")
    print("=" * 70)
    
    desc_nonzero = [d for d in desc_lengths if d > 0]
    print(f"\n  Taxa with descriptions: {len(desc_nonzero):,}")
    print(f"  Taxa without descriptions: {total - len(desc_nonzero):,}")
    
    if desc_nonzero:
        print(f"\n  Min: {min(desc_nonzero):,} chars")
        print(f"  Max: {max(desc_nonzero):,} chars")
        print(f"  Mean: {sum(desc_nonzero)/len(desc_nonzero):,.0f} chars")
        print(f"  Median: {percentile(desc_nonzero, 50):,.0f} chars")
        
        print("\n  Percentiles:")
        for p in [10, 25, 50, 75, 90, 95, 99]:
            val = percentile(desc_nonzero, p)
            print(f"    P{p:2}: {val:>10,.0f} chars")
    
    print("\n" + "=" * 70)
    print("SECTION COUNT DISTRIBUTION")
    print("=" * 70)
    
    section_dist = {}
    for s in section_counts:
        section_dist[s] = section_dist.get(s, 0) + 1
    
    print("\n  Section count breakdown:")
    for s in sorted(section_dist.keys())[:15]:
        count = section_dist[s]
        bar = "█" * min(int(count / total * 200), 50)
        print(f"    {s:2} sections: {count:>8,} ({count/total*100:5.1f}%) {bar}")
    if max(section_dist.keys()) > 15:
        remaining = sum(c for s, c in section_dist.items() if s > 15)
        print(f"    15+ sections: {remaining:>7,}")
    
    print("\n" + "=" * 70)
    print("VERNACULAR NAME PRESENCE")
    print("=" * 70)
    
    no_vernacular = total - has_vernacular_count
    print(f"\n  Has vernacular name: {has_vernacular_count:,} ({has_vernacular_count/total*100:.1f}%)")
    print(f"  No vernacular name:  {no_vernacular:,} ({no_vernacular/total*100:.1f}%)")
    
    print("\n" + "=" * 70)
    print("MULTIMEDIA COUNT DISTRIBUTION")
    print("=" * 70)
    
    mm_nonzero = [m for m in multimedia_counts if m > 0]
    no_mm = total - len(mm_nonzero)
    print(f"\n  Taxa with images: {len(mm_nonzero):,} ({len(mm_nonzero)/total*100:.1f}%)")
    print(f"  Taxa without images: {no_mm:,} ({no_mm/total*100:.1f}%)")
    
    if mm_nonzero:
        mm_dist = {}
        for m in mm_nonzero:
            key = min(m, 10)  # Cap at 10+
            mm_dist[key] = mm_dist.get(key, 0) + 1
        
        print("\n  Image count breakdown (for taxa with images):")
        for m in sorted(mm_dist.keys()):
            count = mm_dist[m]
            label = f"{m:2}" if m < 10 else "10+"
            bar = "█" * min(int(count / len(mm_nonzero) * 100), 50)
            print(f"    {label} images: {count:>7,} ({count/len(mm_nonzero)*100:5.1f}%) {bar}")
    
    print("\n" + "=" * 70)
    print("SUGGESTED NEW THRESHOLDS")
    print("=" * 70)
    
    print("\n  Option 1: Top percentile-based")
    print(f"    Easy   = Top 5%  (score >= {percentile(scores, 95):.0f}): ~{int(total*0.05):,} taxa")
    print(f"    Medium = Top 20% (score >= {percentile(scores, 80):.0f}): ~{int(total*0.15):,} taxa")
    print(f"    Hard   = Top 50% (score >= {percentile(scores, 50):.0f}): ~{int(total*0.30):,} taxa")
    print(f"    Expert = Bottom 50%: ~{int(total*0.50):,} taxa")
    
    print("\n  Option 2: Rounder thresholds")
    for easy_thresh in [70, 75, 80]:
        for medium_thresh in [50, 55, 60]:
            for hard_thresh in [30, 35, 40]:
                easy_count = sum(1 for s in scores if s >= easy_thresh)
                medium_count = sum(1 for s in scores if medium_thresh <= s < easy_thresh)
                hard_count = sum(1 for s in scores if hard_thresh <= s < medium_thresh)
                expert_count = sum(1 for s in scores if s < hard_thresh)
                
                if easy_count > 5000 and medium_count > 20000:  # Only show reasonable options
                    print(f"    Easy >= {easy_thresh}, Medium >= {medium_thresh}, Hard >= {hard_thresh}:")
                    print(f"      Easy: {easy_count:,}, Medium: {medium_count:,}, Hard: {hard_count:,}, Expert: {expert_count:,}")


if __name__ == "__main__":
    main()

