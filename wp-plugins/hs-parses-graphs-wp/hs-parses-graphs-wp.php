<?php
/**
 * Plugin Name:       Hearthstone Parses - Interactive Graphs
 * Description:       Integrates high-performance interactive hsguru meta scatter plots and Vicious Syndicate radars into WordPress via simple shortcodes.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Hearthstone Parses Dev Team
 * License:           MIT
 * Text Domain:       hs-parses-graphs-wp
 * Domain Path:       /languages
 *
 * @package HSParsesGraphsWP
 */

defined( 'ABSPATH' ) || exit;

define( 'HS_PARSES_GRAPHS_VERSION', '1.0.0' );
define( 'HS_PARSES_GRAPHS_DIR', plugin_dir_path( __FILE__ ) );
define( 'HS_PARSES_GRAPHS_URL', plugin_dir_url( __FILE__ ) );

/**
 * Register styles and scripts on init but do not enqueue globally.
 * They will be enqueued dynamically in shortcode callbacks.
 */
add_action( 'wp_enqueue_scripts', 'hs_parses_graphs_register_assets' );
function hs_parses_graphs_register_assets() {
	wp_register_style(
		'hs-parses-graphs-style',
		HS_PARSES_GRAPHS_URL . 'assets/css/graphs.css',
		array(),
		HS_PARSES_GRAPHS_VERSION
	);

	wp_register_script(
		'hs-parses-meta-scatter',
		HS_PARSES_GRAPHS_URL . 'assets/js/meta-scatter.js',
		array(),
		HS_PARSES_GRAPHS_VERSION,
		true
	);

	wp_register_script(
		'hs-parses-vs-radar',
		HS_PARSES_GRAPHS_URL . 'assets/js/vs-radar.js',
		array(),
		HS_PARSES_GRAPHS_VERSION,
		true
	);
}

/**
 * Register Shortcodes
 */
add_action( 'init', 'hs_parses_graphs_register_shortcodes' );
function hs_parses_graphs_register_shortcodes() {
	add_shortcode( 'hs_meta_scatter_chart', 'hs_parses_render_meta_scatter' );
	add_shortcode( 'hs_vs_radar_chart', 'hs_parses_render_vs_radar' );
}

/**
 * Render HSGuru Meta Scatter Plot Shortcode
 * Format: [hs_meta_scatter_chart source="hsguru_meta_standard_diamond_4to1" api_url="https://api.hs-manacost.ru" width="850" height="500"]
 */
function hs_parses_render_meta_scatter( $atts ) {
	$default_api = 'https://api.hs-manacost.ru';

	$a = shortcode_atts(
		array(
			'source'  => 'hsguru_meta_standard_diamond_4to1',
			'api_url' => $default_api,
			'width'   => '850',
			'height'  => '500',
		),
		$atts,
		'hs_meta_scatter_chart'
	);

	// Sanitize and validate inputs
	$source  = sanitize_key( $a['source'] );
	$api_url = esc_url_raw( $a['api_url'] );
	$width   = absint( $a['width'] );
	$height  = absint( $a['height'] );

	// Dynamically enqueue scripts only when shortcode is rendered
	wp_enqueue_style( 'hs-parses-graphs-style' );
	wp_enqueue_script( 'hs-parses-meta-scatter' );

	ob_start();
	?>
	<div class="hs-meta-scatter-wrapper" 
		data-api-url="<?php echo esc_url( $api_url ); ?>" 
		data-source-id="<?php echo esc_attr( $source ); ?>">
		
		<p class="muted">
			<?php echo esc_html__( 'Интерактивный график распределения метагейма (Винрейт / Популярность). По вертикали — популярность (%), по горизонтали — процент побед (%). Наведите курсор на точку для подробной статистики.', 'hs-parses-graphs-wp' ); ?>
		</p>
		
		<div class="hs-meta-scatter-canvas-container" style="background: #1e1e24; border-radius: 8px; padding: 10px; border: 1px solid var(--hs-graph-border);">
			<canvas class="hs-meta-scatter-canvas" 
				width="<?php echo esc_attr( $width ); ?>" 
				height="<?php echo esc_attr( $height ); ?>" 
				style="background: #1e1e24; border-radius: 6px; aspect-ratio: <?php echo esc_attr( $width ); ?>/<?php echo esc_attr( $height ); ?>;"></canvas>
		</div>
		
		<div class="hs-meta-scatter-tooltip">
			<?php echo esc_html__( 'Наведите на точку, чтобы увидеть детали', 'hs-parses-graphs-wp' ); ?>
		</div>
	</div>
	<?php
	return ob_get_clean();
}

/**
 * Render Vicious Syndicate Radar Shortcode
 * Format: [hs_vs_radar_chart api_url="https://api.hs-manacost.ru" width="750" height="750"]
 */
function hs_parses_render_vs_radar( $atts ) {
	$default_api = 'https://api.hs-manacost.ru';

	$a = shortcode_atts(
		array(
			'api_url' => $default_api,
			'width'   => '750',
			'height'  => '750',
		),
		$atts,
		'hs_vs_radar_chart'
	);

	// Sanitize and validate inputs
	$api_url = esc_url_raw( $a['api_url'] );
	$width   = absint( $a['width'] );
	$height  = absint( $a['height'] );

	// Dynamically enqueue scripts only when shortcode is rendered
	wp_enqueue_style( 'hs-parses-graphs-style' );
	wp_enqueue_script( 'hs-parses-vs-radar' );

	ob_start();
	?>
	<div class="hs-vs-radar-wrapper" data-api-url="<?php echo esc_url( $api_url ); ?>">
		
		<p class="muted">
			<?php echo esc_html__( 'Интерактивный радар синергии карт (Vicious Syndicate Radar Graph). Выберите класс и конкретный архетип. Перетаскивайте узлы мышью или нажимайте на них для просмотра связей.', 'hs-parses-graphs-wp' ); ?>
		</p>

		<!-- Class Tab Buttons -->
		<div class="hs-vs-class-tabs"></div>
		
		<!-- Archetype Tab Buttons -->
		<div class="hs-vs-archetype-tabs"></div>

		<!-- Deck Code section -->
		<div class="hs-vs-deck-code-section" style="margin: 15px 0; display: none; background: rgba(255,255,255,0.03); padding: 12px; border: 1px dashed var(--hs-graph-border); border-radius: 8px;">
			<span style="font-size: 0.9rem; margin-right: 10px; color: var(--hs-graph-accent); font-weight: bold;">
				<?php echo esc_html__( 'Код колоды:', 'hs-parses-graphs-wp' ); ?>
			</span>
			<input type="text" class="hs-vs-deck-code-input" readonly style="width: 250px; max-width: calc(100% - 130px); background: #1a1a24; border: 1px solid var(--hs-graph-border); color: #fff; padding: 6px 10px; border-radius: 6px; font-size: 0.85rem;" />
			<button class="hs-vs-deck-code-copy-btn" style="background: #2ec4b6; border: none; color: #fff; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; font-weight: bold; margin-left: 5px;">
				<?php echo esc_html__( 'Копировать', 'hs-parses-graphs-wp' ); ?>
			</button>
		</div>

		<div style="display: flex; gap: 20px; flex-wrap: wrap; margin-top: 20px;">
			<!-- Canvas Graph -->
			<div style="flex: 1; min-width: 300px; max-width: <?php echo esc_attr( $width ); ?>px;">
				<div style="background: #111113; border-radius: 8px; padding: 10px; border: 1px solid var(--hs-graph-border);">
					<canvas class="hs-vs-radar-canvas" 
						width="750" 
						height="750" 
						style="background: #111113; border-radius: 6px; width: 100%; max-width: 750px; aspect-ratio: 1; display: block; cursor: grab;"></canvas>
				</div>
				<div class="hs-vs-radar-hover-info" style="margin-top: 10px; text-align: center; color: var(--hs-graph-muted); font-size: 0.9rem;">
					<?php echo esc_html__( 'Наведите на карту для деталей', 'hs-parses-graphs-wp' ); ?>
				</div>
			</div>

			<!-- Node Info Panel -->
			<div style="width: 320px; max-width: 100%; display: flex; flex-direction: column; gap: 15px;">
				<!-- Search -->
				<div>
					<input type="text" class="hs-vs-radar-search" placeholder="<?php echo esc_attr__( 'Поиск карты...', 'hs-parses-graphs-wp' ); ?>" style="width: 100%; background: #1e1e24; border: 1px solid var(--hs-graph-border); padding: 8px 12px; border-radius: 6px; color: #fff; font-size: 0.9rem;" />
				</div>

				<!-- Selected Card Details -->
				<div class="hs-vs-selected-card-panel" style="background: rgba(255,255,255,0.02); border: 1px solid var(--hs-graph-border); border-radius: 8px; padding: 15px;">
					<h4 class="hs-vs-selected-card-title" style="margin-top: 0; font-size: 0.95rem; color: var(--hs-graph-accent);">
						<?php echo esc_html__( 'Выберите карту на графе', 'hs-parses-graphs-wp' ); ?>
					</h4>
					<div class="hs-vs-selected-card-details" style="font-size: 0.85rem; color: #ccc;">
						<?php echo esc_html__( 'Нажмите на любой узел на графе, чтобы увидеть его сильные связи с другими картами.', 'hs-parses-graphs-wp' ); ?>
					</div>
				</div>

				<!-- Nodes Table List -->
				<div style="max-height: 280px; overflow-y: auto; border: 1px solid var(--hs-graph-border); border-radius: 8px;">
					<table class="hs-vs-nodes-table" style="width: 100%; font-size: 0.8rem; border-collapse: collapse; background: #1e1e24;">
						<thead>
							<tr style="border-bottom: 1px solid var(--hs-graph-border); background: #242430; color: var(--hs-graph-muted);">
								<th style="padding: 6px 8px; text-align: left;"><?php echo esc_html__( 'Карта', 'hs-parses-graphs-wp' ); ?></th>
								<th style="padding: 6px 8px; text-align: left;"><?php echo esc_html__( 'Поп.', 'hs-parses-graphs-wp' ); ?></th>
								<th style="padding: 6px 8px; text-align: left;"><?php echo esc_html__( 'Связей', 'hs-parses-graphs-wp' ); ?></th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
				</div>

				<button class="hs-vs-radar-reset-btn" style="background: #e71d36; border: none; color: #fff; padding: 10px; border-radius: 6px; cursor: pointer; font-weight: bold; width: 100%; font-size: 0.85rem; transition: background 0.2s;">
					<?php echo esc_html__( 'Сбросить фильтры', 'hs-parses-graphs-wp' ); ?>
				</button>
			</div>
		</div>
	</div>
	<?php
	return ob_get_clean();
}
