#!/usr/bin/env python3
"""Plot popularity score distributions for Wikipedia species entries.

This script generates histograms showing the distribution of:
- Overall popularity scores
- Description length
- Section count
- Vernacular name presence
- Multimedia count

Usage:
    python examples/plot_popularity_distribution.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import matplotlib.pyplot as plt
import numpy as np

from taxonomica.popularity import PopularityIndex


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
    has_vernacular = []
    multimedia_counts = []
    
    print("Collecting metrics...")
    for metrics in index._by_id.values():
        scores.append(metrics.popularity_score)
        desc_lengths.append(metrics.description_length)
        section_counts.append(metrics.section_count)
        has_vernacular.append(1 if metrics.has_vernacular else 0)
        multimedia_counts.append(metrics.multimedia_count)
    
    print(f"Total taxa: {len(scores):,}")
    
    # Create figure with subplots
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle("Wikipedia Species Popularity Metrics Distribution", fontsize=14, fontweight='bold')
    
    # 1. Overall popularity score histogram
    ax1 = axes[0, 0]
    ax1.hist(scores, bins=50, color='steelblue', edgecolor='white', alpha=0.8)
    ax1.axvline(x=20, color='red', linestyle='--', label='Expert/Hard (20)')
    ax1.axvline(x=40, color='orange', linestyle='--', label='Hard/Medium (40)')
    ax1.axvline(x=60, color='green', linestyle='--', label='Medium/Easy (60)')
    ax1.set_xlabel('Popularity Score (0-100)')
    ax1.set_ylabel('Count')
    ax1.set_title('Overall Popularity Score')
    ax1.legend(fontsize=8)
    
    # Add tier counts as text
    tier_counts = index.get_stats()
    text = f"Easy: {tier_counts['easy']:,}\nMedium: {tier_counts['medium']:,}\nHard: {tier_counts['hard']:,}\nExpert: {tier_counts['expert']:,}"
    ax1.text(0.95, 0.95, text, transform=ax1.transAxes, fontsize=9,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # 2. Description length histogram (linear scale, capped for readability)
    ax2 = axes[0, 1]
    desc_lengths_nonzero = [d for d in desc_lengths if d > 0]
    # Cap at 10,000 chars for better visualization (95th percentile is ~4000)
    desc_capped = [min(d, 10000) for d in desc_lengths_nonzero]
    ax2.hist(desc_capped, bins=50, color='coral', edgecolor='white', alpha=0.8)
    ax2.set_xlabel('Description Length (chars, capped at 10K)')
    ax2.set_ylabel('Count')
    ax2.set_title('Description Length')
    
    # Add percentiles
    percentiles = [25, 50, 75, 90, 95]
    desc_arr = np.array(desc_lengths_nonzero)
    pct_text = "\n".join([f"P{p}: {int(np.percentile(desc_arr, p)):,}" for p in percentiles])
    ax2.text(0.95, 0.95, pct_text, transform=ax2.transAxes, fontsize=9,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # 3. Section count histogram
    ax3 = axes[0, 2]
    max_sections = min(max(section_counts), 20)  # Cap at 20 for readability
    ax3.hist([min(s, max_sections) for s in section_counts], 
             bins=range(0, max_sections + 2), color='mediumseagreen', edgecolor='white', alpha=0.8)
    ax3.set_xlabel('Section Count')
    ax3.set_ylabel('Count')
    ax3.set_title('Section Count (capped at 20)')
    
    # Add stats
    sec_arr = np.array(section_counts)
    stats_text = f"Mean: {sec_arr.mean():.1f}\nMedian: {np.median(sec_arr):.0f}\nMax: {sec_arr.max()}"
    ax3.text(0.95, 0.95, stats_text, transform=ax3.transAxes, fontsize=9,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # 4. Vernacular name presence (pie chart)
    ax4 = axes[1, 0]
    vn_counts = [sum(has_vernacular), len(has_vernacular) - sum(has_vernacular)]
    ax4.pie(vn_counts, labels=['Has Vernacular', 'No Vernacular'], 
            autopct='%1.1f%%', colors=['lightgreen', 'lightcoral'])
    ax4.set_title('Vernacular Name Presence')
    
    # 5. Multimedia count histogram
    ax5 = axes[1, 1]
    mm_nonzero = [m for m in multimedia_counts if m > 0]
    max_mm = min(max(mm_nonzero) if mm_nonzero else 1, 20)  # Cap at 20
    ax5.hist([min(m, max_mm) for m in mm_nonzero], 
             bins=range(0, max_mm + 2), color='mediumpurple', edgecolor='white', alpha=0.8)
    ax5.set_xlabel('Multimedia Count')
    ax5.set_ylabel('Count')
    ax5.set_title(f'Multimedia Count (taxa with images, capped at 20)')
    
    # Add stats
    has_mm = len(mm_nonzero)
    no_mm = len(multimedia_counts) - has_mm
    mm_text = f"With images: {has_mm:,}\nNo images: {no_mm:,}"
    ax5.text(0.95, 0.95, mm_text, transform=ax5.transAxes, fontsize=9,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # 6. Score breakdown by component (stacked area or grouped bar)
    ax6 = axes[1, 2]
    
    # Sample some data points to show score components
    sample_indices = np.linspace(0, len(scores)-1, 100, dtype=int)
    sorted_indices = np.argsort(scores)
    sample_indices = sorted_indices[np.linspace(0, len(sorted_indices)-1, 100, dtype=int)]
    
    # Calculate component scores for samples
    import math
    sample_desc_scores = []
    sample_section_scores = []
    sample_vn_scores = []
    sample_mm_scores = []
    
    all_metrics = list(index._by_id.values())
    for idx in sample_indices:
        m = all_metrics[idx]
        # Description component (0-20) - reduced from 40
        if m.description_length > 0:
            desc_score = min(20, math.log10(m.description_length) * 6.5)
        else:
            desc_score = 0
        # Section component (0-10) - reduced from 20
        sec_score = min(10, m.section_count * 1)
        # Vernacular component (0-25)
        vn_score = 25 if m.has_vernacular else 0
        # Multimedia component (0-30) - doubled from 15
        mm_score = min(30, m.multimedia_count * 6)
        
        sample_desc_scores.append(desc_score)
        sample_section_scores.append(sec_score)
        sample_vn_scores.append(vn_score)
        sample_mm_scores.append(mm_score)
    
    x = range(len(sample_indices))
    ax6.stackplot(x, sample_desc_scores, sample_section_scores, sample_mm_scores, sample_vn_scores,
                  labels=['Description (0-20)', 'Sections (0-10)', 'Multimedia (0-30)', 'Vernacular (0-25)'],
                  colors=['coral', 'mediumseagreen', 'mediumpurple', 'lightgreen'], alpha=0.8)
    ax6.set_xlabel('Taxa (sorted by total score)')
    ax6.set_ylabel('Score Component')
    ax6.set_title('Score Components (stacked)')
    ax6.legend(loc='upper left', fontsize=8)
    ax6.set_xlim(0, len(sample_indices)-1)
    
    plt.tight_layout()
    
    # Save figure
    output_path = Path(__file__).parent / "popularity_distribution.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\nSaved plot to: {output_path}")
    
    # Also print summary statistics
    print("\n" + "=" * 60)
    print("SUMMARY STATISTICS")
    print("=" * 60)
    
    print(f"\nTotal taxa: {len(scores):,}")
    
    print(f"\nPopularity Score:")
    print(f"  Min: {min(scores):.1f}, Max: {max(scores):.1f}")
    print(f"  Mean: {np.mean(scores):.1f}, Median: {np.median(scores):.1f}")
    for p in [10, 25, 50, 75, 90, 95, 99]:
        print(f"  P{p}: {np.percentile(scores, p):.1f}")
    
    print(f"\nCurrent tier thresholds:")
    print(f"  Easy:   score >= 60  ({tier_counts['easy']:,} taxa)")
    print(f"  Medium: score >= 40  ({tier_counts['medium']:,} taxa)")
    print(f"  Hard:   score >= 20  ({tier_counts['hard']:,} taxa)")
    print(f"  Expert: score < 20   ({tier_counts['expert']:,} taxa)")
    
    # Suggest new thresholds based on percentiles
    print(f"\nSuggested thresholds (for more balanced tiers):")
    print(f"  Top 10% (P90={np.percentile(scores, 90):.1f}): ~{int(len(scores)*0.10):,} taxa")
    print(f"  Top 25% (P75={np.percentile(scores, 75):.1f}): ~{int(len(scores)*0.25):,} taxa")
    print(f"  Top 50% (P50={np.percentile(scores, 50):.1f}): ~{int(len(scores)*0.50):,} taxa)")
    
    plt.show()


if __name__ == "__main__":
    main()

