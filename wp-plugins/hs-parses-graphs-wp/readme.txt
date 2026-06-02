=== Hearthstone Parses - Interactive Graphs ===
Contributors: Hearthstone Parses Team
Tags: hearthstone, vicious syndicate, hsguru, graphs, radar, scatter plot, shortcode, interactive, canvas
Requires at least: 6.0
Tested up to: 6.5
Stable tag: 1.0.0
License: MIT
License URI: https://opensource.org/licenses/MIT

Integrates highly optimized interactive charts (such as HSGuru Meta Scatter Plot and Vicious Syndicate Radar Networks) into your WordPress website using safe, high-performance shortcodes.

== Description ==

This plugin provides two key shortcodes to integrate professional interactive Hearthstone data visualizations powered by the Hearthstone Parses API:

1. **[hs_meta_scatter_chart]** - Displays an interactive HTML5 Canvas scatter plot representing the distribution of meta archetypes based on their **Winrate** (X-axis) and **Popularity** (Y-axis), matching the look and feel of hsguru.com. Points are colored according to their Hearthstone class, with rich tooltips on hover.
2. **[hs_vs_radar_chart]** - Displays an interactive force-directed network graph of card synergies matching Vicious Syndicate. It allows selecting classes, choosing specific archetypes, searching for individual cards, and viewing strongest synergy ties.

Both shortcodes only load their JavaScript and CSS assets on pages where they are actually placed, preserving website speed and performance on other pages.

== Installation ==

1. Upload the `hs-parses-graphs-wp` folder to the `/wp-content/plugins/` directory.
2. Activate the plugin through the 'Plugins' menu in WordPress.
3. Place shortcodes on any page, post, or widget area.

== Shortcodes & Attributes ==

=== 1. Meta Scatter Chart ===
`[hs_meta_scatter_chart]`

*   `source` (string) - The source dataset ID. Defaults to `hsguru_meta_standard_diamond_4to1`. Other valid options include:
    *   `hsguru_meta_standard_legend`
    *   `hsguru_meta_standard_diamond_4to1`
    *   `hsguru_meta_standard_top_5k`
    *   `hsguru_meta_standard_top_legend`
    *   `hsguru_meta_wild_legend`
    *   `hsguru_meta_wild_diamond_4to1`
    *   `hsguru_meta_wild_top_legend`
    *   `hsguru_meta_wild_top_5k`
*   `api_url` (string) - The Hearthstone Parses API URL. Defaults to `https://api.hs-manacost.ru`.
*   `width` (integer) - Width of the canvas. Defaults to `850`.
*   `height` (integer) - Height of the canvas. Defaults to `500`.

*Example:*
`[hs_meta_scatter_chart source="hsguru_meta_standard_legend" width="850" height="500"]`

=== 2. Vicious Syndicate Radar Chart ===
`[hs_vs_radar_chart]`

*   `api_url` (string) - The Hearthstone Parses API URL. Defaults to `https://api.hs-manacost.ru`.
*   `width` (integer) - Maximum width of the canvas. Defaults to `750`.
*   `height` (integer) - Maximum height of the canvas. Defaults to `750`.

*Example:*
`[hs_vs_radar_chart api_url="https://api.hs-manacost.ru"]`

== Changelog ==

= 1.0.0 =
* Initial release of the plugin supporting interactive HTML5 Canvas scatter plots and force-directed radars.
