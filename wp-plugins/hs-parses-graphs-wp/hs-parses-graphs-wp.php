<?php
/**
 * Plugin Name:       Hearthstone Parses - Interactive Graphs
 * Description:       Integrates high-performance interactive hsguru meta scatter plots (Standard/Wild) and Vicious Syndicate radars into WordPress via simple shortcodes.
 * Version:           1.1.0
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

define( 'HS_PARSES_GRAPHS_VERSION', '1.1.0' );
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
	// Backward compatibility
	add_shortcode( 'hs_meta_scatter_chart', 'hs_parses_render_meta_scatter' );
	
	// Modern format-specific scatter charts
	add_shortcode( 'hs_meta_scatter_standard', 'hs_parses_render_meta_scatter_standard' );
	add_shortcode( 'hs_meta_scatter_wild', 'hs_parses_render_meta_scatter_wild' );
	
	// Vicious Syndicate synergy radars
	add_shortcode( 'hs_vs_radar_chart', 'hs_parses_render_vs_radar' );
}

/**
 * Helper to get the default api domain
 */
function hs_parses_graphs_get_default_api_url() {
	return 'https://api.hs-manacost.ru';
}

/**
 * Render HSGuru Meta Scatter Plot Shortcode (Generic / Backward Compatibility)
 */
function hs_meta_scatter_chart( $atts ) {
	return hs_parses_render_meta_scatter( $atts );
}

function hs_parses_render_meta_scatter( $atts ) {
	$a = shortcode_atts(
		array(
			'source'        => 'hsguru_meta_standard_diamond_4to1',
			'api_url'       => hs_parses_graphs_get_default_api_url(),
			'width'         => '850',
			'height'        => '500',
			'show_selector' => 'yes',
		),
		$atts,
		'hs_meta_scatter_chart'
	);

	$source        = sanitize_key( $a['source'] );
	$api_url       = esc_url_raw( $a['api_url'] );
	$width         = absint( $a['width'] );
	$height        = absint( $a['height'] );
	$show_selector = sanitize_key( $a['show_selector'] );

	// Determine format and rank from legacy source name
	$format = 'standard';
	$rank   = 'diamond_4to1';
	if ( strpos( $source, '_wild_' ) !== false ) {
		$format = 'wild';
	}
	if ( strpos( $source, '_legend' ) !== false ) {
		$rank = 'legend';
	} elseif ( strpos( $source, '_top_5k' ) !== false ) {
		$rank = 'top_5k';
	} elseif ( strpos( $source, '_top_legend' ) !== false ) {
		$rank = 'top_legend';
	}

	wp_enqueue_style( 'hs-parses-graphs-style' );
	wp_enqueue_script( 'hs-parses-meta-scatter' );

	ob_start();
	?>
	<div class="hs-meta-scatter-wrapper" 
		data-api-url="<?php echo esc_url( $api_url ); ?>" 
		data-format="<?php echo esc_attr( $format ); ?>"
		data-start-rank="<?php echo esc_attr( $rank ); ?>"
		data-show-selector="<?php echo esc_attr( $show_selector ); ?>">
		
		<p class="muted">
			<?php echo esc_html__( 'Интерактивный график распределения метагейма (Винрейт / Популярность). По вертикали — популярность (%), по горизонтали — процент побед (%). Выберите нужный ранг ниже.', 'hs-parses-graphs-wp' ); ?>
		</p>

		<?php if ( 'yes' === $show_selector ) : ?>
			<div class="hs-meta-scatter-rank-selector" style="margin-bottom: 15px; display: flex; gap: 8px; flex-wrap: wrap;"></div>
		<?php endif; ?>
		
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
 * Render Standard Format Scatter Plot
 * [hs_meta_scatter_standard rank="diamond_4to1" show_selector="yes"]
 */
function hs_parses_render_meta_scatter_standard( $atts ) {
	$a = shortcode_atts(
		array(
			'rank'          => 'diamond_4to1',
			'api_url'       => hs_parses_graphs_get_default_api_url(),
			'width'         => '850',
			'height'        => '500',
			'show_selector' => 'yes',
		),
		$atts,
		'hs_meta_scatter_standard'
	);

	$rank          = sanitize_key( $a['rank'] );
	$api_url       = esc_url_raw( $a['api_url'] );
	$width         = absint( $a['width'] );
	$height        = absint( $a['height'] );
	$show_selector = sanitize_key( $a['show_selector'] );

	wp_enqueue_style( 'hs-parses-graphs-style' );
	wp_enqueue_script( 'hs-parses-meta-scatter' );

	ob_start();
	?>
	<div class="hs-meta-scatter-wrapper" 
		data-api-url="<?php echo esc_url( $api_url ); ?>" 
		data-format="standard"
		data-start-rank="<?php echo esc_attr( $rank ); ?>"
		data-show-selector="<?php echo esc_attr( $show_selector ); ?>">
		
		<p class="muted">
			<strong><?php echo esc_html__( 'Стандартный формат (Standard):', 'hs-parses-graphs-wp' ); ?></strong>
			<?php echo esc_html__( 'Интерактивный мета-график. Выберите ранг для отображения распределения сил архетипов.', 'hs-parses-graphs-wp' ); ?>
		</p>

		<?php if ( 'yes' === $show_selector ) : ?>
			<div class="hs-meta-scatter-rank-selector" style="margin-bottom: 15px; display: flex; gap: 8px; flex-wrap: wrap;"></div>
		<?php endif; ?>
		
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
 * Render Wild Format Scatter Plot
 * [hs_meta_scatter_wild rank="legend" show_selector="yes"]
 */
function hs_parses_render_meta_scatter_wild( $atts ) {
	$a = shortcode_atts(
		array(
			'rank'          => 'legend',
			'api_url'       => hs_parses_graphs_get_default_api_url(),
			'width'         => '850',
			'height'        => '500',
			'show_selector' => 'yes',
		),
		$atts,
		'hs_meta_scatter_wild'
	);

	$rank          = sanitize_key( $a['rank'] );
	$api_url       = esc_url_raw( $a['api_url'] );
	$width         = absint( $a['width'] );
	$height        = absint( $a['height'] );
	$show_selector = sanitize_key( $a['show_selector'] );

	wp_enqueue_style( 'hs-parses-graphs-style' );
	wp_enqueue_script( 'hs-parses-meta-scatter' );

	ob_start();
	?>
	<div class="hs-meta-scatter-wrapper" 
		data-api-url="<?php echo esc_url( $api_url ); ?>" 
		data-format="wild"
		data-start-rank="<?php echo esc_attr( $rank ); ?>"
		data-show-selector="<?php echo esc_attr( $show_selector ); ?>">
		
		<p class="muted">
			<strong><?php echo esc_html__( 'Вольный формат (Wild):', 'hs-parses-graphs-wp' ); ?></strong>
			<?php echo esc_html__( 'Интерактивный мета-график. Выберите ранг для отображения распределения сил архетипов в Вольном режиме.', 'hs-parses-graphs-wp' ); ?>
		</p>

		<?php if ( 'yes' === $show_selector ) : ?>
			<div class="hs-meta-scatter-rank-selector" style="margin-bottom: 15px; display: flex; gap: 8px; flex-wrap: wrap;"></div>
		<?php endif; ?>
		
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
 * Render Vicious Syndicate Radar Shortcode with Class Select & Locks
 * [hs_vs_radar_chart class="Druid" lock_class="no" width="750" height="750"]
 */
function hs_parses_render_vs_radar( $atts ) {
	$a = shortcode_atts(
		array(
			'api_url'    => hs_parses_graphs_get_default_api_url(),
			'class'      => '',
			'lock_class' => 'no',
			'width'      => '750',
			'height'     => '750',
		),
		$atts,
		'hs_vs_radar_chart'
	);

	$api_url    = esc_url_raw( $a['api_url'] );
	$class      = sanitize_key( $a['class'] );
	$lock_class = sanitize_key( $a['lock_class'] );
	$width      = absint( $a['width'] );
	$height     = absint( $a['height'] );

	wp_enqueue_style( 'hs-parses-graphs-style' );
	wp_enqueue_script( 'hs-parses-vs-radar' );

	ob_start();
	?>
	<div class="hs-vs-radar-wrapper" 
		data-api-url="<?php echo esc_url( $api_url ); ?>"
		data-start-class="<?php echo esc_attr( $class ); ?>"
		data-lock-class="<?php echo esc_attr( $lock_class ); ?>">
		
		<p class="muted">
			<?php echo esc_html__( 'Интерактивный радар синергии карт (Vicious Syndicate Radar Graph). Выберите класс и архетип. Перетаскивайте узлы мышью или нажимайте на них для просмотра связей.', 'hs-parses-graphs-wp' ); ?>
		</p>

		<!-- Class Tab Buttons (Automatically hidden in JS if lock_class="yes") -->
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

/**
 * Register Admin Menu under Tools
 */
add_action( 'admin_menu', 'hs_parses_graphs_register_tools_page' );
function hs_parses_graphs_register_tools_page() {
	add_management_page(
		__( 'Графики Hearthstone', 'hs-parses-graphs-wp' ),
		__( 'Графики Hearthstone', 'hs-parses-graphs-wp' ),
		'manage_options',
		'hs-parses-graphs-documentation',
		'hs_parses_graphs_render_tools_page'
	);
}

/**
 * Render the Tools Admin Page Layout
 */
function hs_parses_graphs_render_tools_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'Извините, у вас нет достаточных прав для доступа к этой странице.', 'hs-parses-graphs-wp' ) );
	}
	?>
	<div class="wrap" style="max-width: 1100px; margin-top: 20px; font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen-Sans,Ubuntu,Cantarell,sans-serif;">
		<h1 style="font-weight: 700; margin-bottom: 5px; color: #23282d;">
			<?php echo esc_html__( 'Интерактивные графики Hearthstone', 'hs-parses-graphs-wp' ); ?>
		</h1>
		<p class="description" style="font-size: 1rem; margin-bottom: 25px; color: #555d66;">
			<?php echo esc_html__( 'Руководство и список доступных шорткодов для размещения интерактивных визуализаций HSGuru и Vicious Syndicate.', 'hs-parses-graphs-wp' ); ?>
		</p>

		<!-- Card Layout -->
		<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 30px;">
			
			<!-- Card 1 -->
			<div style="background: #fff; border: 1px solid #ccd0d4; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.04);">
				<span style="display: inline-block; padding: 4px 8px; background: #2ec4b6; color: #fff; font-size: 0.75rem; font-weight: bold; border-radius: 4px; margin-bottom: 12px; text-transform: uppercase;">
					Standard Meta
				</span>
				<h3 style="margin: 0 0 10px 0; font-size: 1.2rem; color: #1e1e1e;">[hs_meta_scatter_standard]</h3>
				<p style="color: #646970; font-size: 0.9rem; line-height: 1.5; min-height: 60px;">
					<?php echo esc_html__( 'Отображает интерактивное распределение винрейта и популярности архетипов Стандартного формата на холсте HTML5 Canvas.', 'hs-parses-graphs-wp' ); ?>
				</p>
				<div style="background: #f6f7f7; padding: 10px; border-radius: 6px; border-left: 4px solid #2ec4b6; margin-bottom: 15px;">
					<code id="sc-code-std" style="font-family: Consolas, Monaco, monospace; font-size: 0.85rem; color: #000;">[hs_meta_scatter_standard rank="diamond_4to1" show_selector="yes"]</code>
				</div>
				<button class="button button-secondary" onclick="copyTextToClipboard('sc-code-std', this)">
					<?php echo esc_html__( 'Скопировать шорткод', 'hs-parses-graphs-wp' ); ?>
				</button>
			</div>

			<!-- Card 2 -->
			<div style="background: #fff; border: 1px solid #ccd0d4; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.04);">
				<span style="display: inline-block; padding: 4px 8px; background: #ff9f1c; color: #000; font-size: 0.75rem; font-weight: bold; border-radius: 4px; margin-bottom: 12px; text-transform: uppercase;">
					Wild Meta
				</span>
				<h3 style="margin: 0 0 10px 0; font-size: 1.2rem; color: #1e1e1e;">[hs_meta_scatter_wild]</h3>
				<p style="color: #646970; font-size: 0.9rem; line-height: 1.5; min-height: 60px;">
					<?php echo esc_html__( 'Отображает интерактивное распределение винрейта и популярности архетипов Вольного формата на холсте HTML5 Canvas.', 'hs-parses-graphs-wp' ); ?>
				</p>
				<div style="background: #f6f7f7; padding: 10px; border-radius: 6px; border-left: 4px solid #ff9f1c; margin-bottom: 15px;">
					<code id="sc-code-wild" style="font-family: Consolas, Monaco, monospace; font-size: 0.85rem; color: #000;">[hs_meta_scatter_wild rank="legend" show_selector="yes"]</code>
				</div>
				<button class="button button-secondary" onclick="copyTextToClipboard('sc-code-wild', this)">
					<?php echo esc_html__( 'Скопировать шорткод', 'hs-parses-graphs-wp' ); ?>
				</button>
			</div>

			<!-- Card 3 -->
			<div style="background: #fff; border: 1px solid #ccd0d4; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.04);">
				<span style="display: inline-block; padding: 4px 8px; background: #e71d36; color: #fff; font-size: 0.75rem; font-weight: bold; border-radius: 4px; margin-bottom: 12px; text-transform: uppercase;">
					Synergy Radar
				</span>
				<h3 style="margin: 0 0 10px 0; font-size: 1.2rem; color: #1e1e1e;">[hs_vs_radar_chart]</h3>
				<p style="color: #646970; font-size: 0.9rem; line-height: 1.5; min-height: 60px;">
					<?php echo esc_html__( 'Отображает интерактивный физический граф синергий карт Vicious Syndicate с выбором класса и архетипов.', 'hs-parses-graphs-wp' ); ?>
				</p>
				<div style="background: #f6f7f7; padding: 10px; border-radius: 6px; border-left: 4px solid #e71d36; margin-bottom: 15px;">
					<code id="sc-code-radar" style="font-family: Consolas, Monaco, monospace; font-size: 0.85rem; color: #000;">[hs_vs_radar_chart class="Druid" lock_class="yes"]</code>
				</div>
				<button class="button button-secondary" onclick="copyTextToClipboard('sc-code-radar', this)">
					<?php echo esc_html__( 'Скопировать шорткод', 'hs-parses-graphs-wp' ); ?>
				</button>
			</div>

		</div>

		<!-- Advanced attributes reference -->
		<div style="background: #fff; border: 1px solid #ccd0d4; border-radius: 8px; padding: 25px; box-shadow: 0 1px 3px rgba(0,0,0,.04); margin-bottom: 30px;">
			<h2 style="font-size: 1.3rem; font-weight: bold; margin-top: 0; margin-bottom: 15px; color: #1e1e1e;">
				<?php echo esc_html__( 'Подробная спецификация параметров шорткодов', 'hs-parses-graphs-wp' ); ?>
			</h2>

			<table class="wp-list-table widefat fixed striped pages" style="border: 1px solid #e5e5e5; box-shadow: none; border-radius: 4px; overflow: hidden; margin-bottom: 20px;">
				<thead>
					<tr>
						<th style="font-weight: bold; padding: 10px 15px;"><?php echo esc_html__( 'Параметр', 'hs-parses-graphs-wp' ); ?></th>
						<th style="font-weight: bold; padding: 10px 15px;"><?php echo esc_html__( 'Допустимые значения', 'hs-parses-graphs-wp' ); ?></th>
						<th style="font-weight: bold; padding: 10px 15px;"><?php echo esc_html__( 'Описание', 'hs-parses-graphs-wp' ); ?></th>
					</tr>
				</thead>
				<tbody>
					<!-- Rank -->
					<tr>
						<td style="padding: 12px 15px;"><strong><code>rank</code></strong></td>
						<td style="padding: 12px 15px;"><code>top_legend</code>, <code>top_5k</code>, <code>legend</code>, <code>diamond_4to1</code></td>
						<td style="padding: 12px 15px;">
							<?php echo esc_html__( 'Определяет стартовый ранг данных при загрузке страницы. По умолчанию используется diamond_4to1.', 'hs-parses-graphs-wp' ); ?>
						</td>
					</tr>
					<!-- Show Selector -->
					<tr>
						<td style="padding: 12px 15px;"><strong><code>show_selector</code></strong></td>
						<td style="padding: 12px 15px;"><code>yes</code>, <code>no</code></td>
						<td style="padding: 12px 15px;">
							<?php echo esc_html__( 'Показывает или скрывает кнопки быстрого переключения рангов непосредственно на странице (по умолчанию yes).', 'hs-parses-graphs-wp' ); ?>
						</td>
					</tr>
					<!-- Class -->
					<tr>
						<td style="padding: 12px 15px;"><strong><code>class</code></strong></td>
						<td style="padding: 12px 15px;"><code>DeathKnight</code>, <code>DemonHunter</code>, <code>Druid</code>, <code>Hunter</code>, <code>Mage</code>, <code>Paladin</code>, <code>Priest</code>, <code>Rogue</code>, <code>Shaman</code>, <code>Warlock</code>, <code>Warrior</code></td>
						<td style="padding: 12px 15px;">
							<?php echo esc_html__( 'Стартовый класс для предвыбора во Vicious Syndicate радаре. Позволяет мгновенно открывать конкретную класс-карту при загрузке.', 'hs-parses-graphs-wp' ); ?>
						</td>
					</tr>
					<!-- Lock Class -->
					<tr>
						<td style="padding: 12px 15px;"><strong><code>lock_class</code></strong></td>
						<td style="padding: 12px 15px;"><code>yes</code>, <code>no</code></td>
						<td style="padding: 12px 15px;">
							<?php echo esc_html__( 'Если установлено в "yes", скрывает глобальные вкладки выбора классов, фиксируя радар на одном выбранном классе (с возможностью переключения его архетипов). Отлично подходит для класс-специфичных постов.', 'hs-parses-graphs-wp' ); ?>
						</td>
					</tr>
					<!-- Width/Height -->
					<tr>
						<td style="padding: 12px 15px;"><strong><code>width</code> / <code>height</code></strong></td>
						<td style="padding: 12px 15px;">Числа в пикселях (например, <code>850</code>, <code>500</code>)</td>
						<td style="padding: 12px 15px;">
							<?php echo esc_html__( 'Управляет размерами и соотношением сторон холста интерактивных Canvas графиков.', 'hs-parses-graphs-wp' ); ?>
						</td>
					</tr>
				</tbody>
			</table>

			<div style="background: #f0f6fc; border-left: 4px solid #72aee6; padding: 15px; border-radius: 4px;">
				<h4 style="margin-top: 0; margin-bottom: 5px; color: #1d2327; font-weight: bold;"><?php echo esc_html__( 'Премиальная совместимость с темами Blocksy и Newspaper', 'hs-parses-graphs-wp' ); ?></h4>
				<p style="margin: 0; color: #2c3338; font-size: 0.9rem; line-height: 1.4;">
					<?php echo esc_html__( 'Стили плагина полностью изолированы и используют гибкую адаптивную верстку CSS Grid, Flexbox и CSS Variables. Настройка корректно наследует шрифты темы, прекрасно работает как на светлых, так и на темных макетах, а также поддерживает адаптивный рендеринг на мобильных дисплеях.', 'hs-parses-graphs-wp' ); ?>
				</p>
			</div>
		</div>
	</div>

	<!-- Copy scripts -->
	<script>
		function copyTextToClipboard(elementId, btn) {
			var text = document.getElementById(elementId).textContent;
			navigator.clipboard.writeText(text).then(function() {
				var oldLabel = btn.textContent;
				btn.textContent = '<?php echo esc_js( __( 'Успешно скопировано!', 'hs-parses-graphs-wp' ) ); ?>';
				btn.style.background = '#46b450';
				btn.style.color = '#fff';
				btn.style.borderColor = '#46b450';
				setTimeout(function() {
					btn.textContent = oldLabel;
					btn.style.background = '';
					btn.style.color = '';
					btn.style.borderColor = '';
				}, 1500);
			});
		}
	</script>
	<?php
}
EOF
)",old_string: