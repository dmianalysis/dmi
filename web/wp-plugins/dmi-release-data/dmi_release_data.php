<?php
/*
Plugin Name: DMI Release Data
Description: Renders DMI release data from releases.json
Version: 0.3.0
Author: Thomas C. Williams
*/

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! function_exists( 'tcw_dmi_format_number' ) ) {
	function tcw_dmi_format_number( $value, $decimals = 2 ) {
		if ( ! is_numeric( $value ) ) {
			return '';
		}
		return number_format_i18n( (float) $value, $decimals );
	}
}

if ( ! function_exists( 'tcw_dmi_format_date' ) ) {
	function tcw_dmi_format_date( $value ) {
		if ( empty( $value ) ) {
			return '';
		}
		$ts = strtotime( $value );
		return $ts ? date_i18n( 'F j, Y', $ts ) : $value;
	}
}

if ( ! function_exists( 'tcw_dmi_get_income_pressure_spread' ) ) {
	function tcw_dmi_get_income_pressure_spread( $metrics ) {
		if ( ! is_array( $metrics ) ) {
			return null;
		}

		// Schema 2.0.0+: explicit nonnegative spread.
		if ( isset( $metrics['income_pressure_spread'] ) && is_numeric( $metrics['income_pressure_spread'] ) ) {
			return (float) $metrics['income_pressure_spread'];
		}

		// Legacy schema: income_pressure_gap was effectively a signed Q1-Q5 tilt
		// in some releases, so use abs() when presenting it as a spread.
		if ( isset( $metrics['income_pressure_gap'] ) && is_numeric( $metrics['income_pressure_gap'] ) ) {
			return abs( (float) $metrics['income_pressure_gap'] );
		}

		return null;
	}
}

if ( ! function_exists( 'tcw_dmi_get_income_pressure_tilt' ) ) {
	function tcw_dmi_get_income_pressure_tilt( $metrics ) {
		if ( ! is_array( $metrics ) ) {
			return null;
		}

		// Schema 2.0.0+: explicit signed Q1-Q5 tilt.
		if ( isset( $metrics['income_pressure_tilt'] ) && is_numeric( $metrics['income_pressure_tilt'] ) ) {
			return (float) $metrics['income_pressure_tilt'];
		}

		// Legacy schema fallback: preserve sign if income_pressure_gap exists.
		if ( isset( $metrics['income_pressure_gap'] ) && is_numeric( $metrics['income_pressure_gap'] ) ) {
			return (float) $metrics['income_pressure_gap'];
		}

		return null;
	}
}

if ( ! function_exists( 'tcw_dmi_release_compare' ) ) {
	function tcw_dmi_release_compare( $a, $b ) {
		$a_id = isset( $a['release_id'] ) ? (string) $a['release_id'] : '';
		$b_id = isset( $b['release_id'] ) ? (string) $b['release_id'] : '';
		return strcmp( $b_id, $a_id ); // descending YYYY-MM
	}
}

if ( ! function_exists( 'tcw_dmi_render_links' ) ) {
	function tcw_dmi_render_links( $urls ) {
		$links = array();

		if ( ! empty( $urls['csv'] ) ) {
			$links[] = '<a href="' . esc_url( $urls['csv'] ) . '">CSV</a>';
		}
		if ( ! empty( $urls['parquet'] ) ) {
			$links[] = '<a href="' . esc_url( $urls['parquet'] ) . '">Parquet</a>';
		}
		if ( ! empty( $urls['release_note'] ) ) {
			$links[] = '<a href="' . esc_url( $urls['release_note'] ) . '">Release note</a>';
		}
		if ( ! empty( $urls['dashboard'] ) ) {
			$links[] = '<a href="' . esc_url( $urls['dashboard'] ) . '">Dashboard</a>';
		}
		if ( ! empty( $urls['repo'] ) ) {
			$links[] = '<a href="' . esc_url( $urls['repo'] ) . '">GitHub</a>';
		}

		return implode( ' | ', $links );
	}
}

if ( ! function_exists( 'tcw_dmi_render_spec_links_table' ) ) {
	function tcw_dmi_render_spec_links_table( $spec_urls ) {
		if ( empty( $spec_urls ) || ! is_array( $spec_urls ) ) {
			return '';
		}

		// Core specification was withdrawn in v0.1.12 (see
		// docs/repair/CORE_WITHDRAWAL.md); only Baseline and Slack-Plus are
		// rendered. Manifests published under 3.x will never carry a Core key.
		$labels = array(
			'baseline'   => 'Baseline',
			'slack_plus' => 'Slack-Plus',
		);

		$notes = array(
			'baseline'   => 'Canonical headline series (U-3, headline CPI)',
			'slack_plus' => 'Uses U-6 instead of U-3',
		);

		$html  = '<table class="tcw-dmi-spec-table">';
		$html .= '<thead><tr><th>Specification</th><th>Downloads</th><th>Notes</th></tr></thead><tbody>';

		foreach ( array( 'baseline', 'slack_plus' ) as $spec_key ) {
			if ( empty( $spec_urls[ $spec_key ] ) || ! is_array( $spec_urls[ $spec_key ] ) ) {
				continue;
			}

			$links = tcw_dmi_render_links( $spec_urls[ $spec_key ] );

			$html .= '<tr>';
			$html .= '<td><strong>' . esc_html( $labels[ $spec_key ] ) . '</strong></td>';
			$html .= '<td>' . ( $links ? $links : 'Not available' ) . '</td>';
			$html .= '<td>' . esc_html( $notes[ $spec_key ] ) . '</td>';
			$html .= '</tr>';
		}

		$html .= '</tbody></table>';

		return $html;
	}
}

if ( ! function_exists( 'tcw_dmi_release_data_shortcode' ) ) {
	function tcw_dmi_release_data_shortcode( $atts = array() ) {
		$manifest_path = trailingslashit( ABSPATH ) . 'data/outputs/releases.json';

		if ( ! file_exists( $manifest_path ) ) {
			return '<p>DMI release data is temporarily unavailable.</p>';
		}

		$json = file_get_contents( $manifest_path );
		if ( false === $json ) {
			return '<p>DMI release data could not be read.</p>';
		}

		$manifest = json_decode( $json, true );
		if ( ! is_array( $manifest ) || empty( $manifest['releases'] ) || ! is_array( $manifest['releases'] ) ) {
			return '<p>DMI release data is temporarily unavailable.</p>';
		}

		$releases = $manifest['releases'];
		usort( $releases, 'tcw_dmi_release_compare' );

		$current_release_id = isset( $manifest['current_release_id'] ) ? (string) $manifest['current_release_id'] : '';
		$current = null;
		$archive = array();

		foreach ( $releases as $release ) {
			$rid    = isset( $release['release_id'] ) ? (string) $release['release_id'] : '';
			$status = isset( $release['status'] ) ? (string) $release['status'] : '';

			if (
				null === $current &&
				(
					( $current_release_id && $rid === $current_release_id ) ||
					( 'current' === $status )
				)
			) {
				$current = $release;
				continue;
			}
		}

		if ( null === $current && ! empty( $releases ) ) {
			$current = $releases[0];
		}

		if ( null === $current ) {
			return '<p>No DMI releases are available yet.</p>';
		}

		foreach ( $releases as $release ) {
			$rid = isset( $release['release_id'] ) ? (string) $release['release_id'] : '';
			if ( $rid !== (string) $current['release_id'] ) {
				$archive[] = $release;
			}
		}

		ob_start();
		?>
		<div class="dmi-release-data">

			<section class="dmi-current-release">
				<h2>Current release</h2>

				<div class="dmi-release-card">
					<p>
						<strong>Release:</strong> <?php echo esc_html( $current['release_id'] ); ?><br>
						<strong>Data through:</strong> <?php echo esc_html( $current['data_through_label'] ); ?><br>
						<strong>Published:</strong> <?php echo esc_html( tcw_dmi_format_date( $current['published_at'] ) ); ?><br>
						<strong>Status:</strong> <?php echo esc_html( ucfirst( $current['status'] ) ); ?><br>
						<strong>Methodology version:</strong> <?php echo esc_html( $current['methodology_version'] ); ?>
					</p>

					<?php if ( ! empty( $current['summary'] ) ) : ?>
						<p><?php echo esc_html( $current['summary'] ); ?></p>
					<?php endif; ?>

					<?php if ( ! empty( $current['spec_urls'] ) && is_array( $current['spec_urls'] ) ) : ?>
						<?php echo tcw_dmi_render_spec_links_table( $current['spec_urls'] ); ?>
					<?php endif; ?>

					<?php if ( ! empty( $current['metrics'] ) && is_array( $current['metrics'] ) ) : ?>
						<?php
						$income_pressure_spread = tcw_dmi_get_income_pressure_spread( $current['metrics'] );
						$income_pressure_tilt   = tcw_dmi_get_income_pressure_tilt( $current['metrics'] );
						?>						
						<h3>Current-release snapshot</h3>
						<ul>
							<li><strong>DMI Median:</strong> <?php echo esc_html( tcw_dmi_format_number( $current['metrics']['dmi_median'] ) ); ?></li>
							<li><strong>DMI Stress:</strong> <?php echo esc_html( tcw_dmi_format_number( $current['metrics']['dmi_stress'] ) ); ?></li>
							<li>
								<strong>Income Pressure Spread (max DMI &minus; min DMI):</strong>
								<?php echo esc_html( null !== $income_pressure_spread ? tcw_dmi_format_number( $income_pressure_spread ) : 'N/A' ); ?>
							</li>

							<li>
								<strong>Income Pressure Tilt (Q1 DMI &minus; Q5 DMI):</strong>
								<?php echo esc_html( null !== $income_pressure_tilt ? tcw_dmi_format_number( $income_pressure_tilt ) : 'N/A' ); ?>
							</li>
							<li><strong>Most-pressured group:</strong> <?php echo esc_html( $current['metrics']['most_pressured_group'] ); ?></li>
							<li><strong>Least-pressured group:</strong> <?php echo esc_html( $current['metrics']['least_pressured_group'] ); ?></li>
							<li><strong>National unemployment:</strong> <?php echo esc_html( tcw_dmi_format_number( $current['metrics']['unemployment'], 1 ) ); ?>%</li>
						</ul>
					<?php endif; ?>
				</div>
			</section>

			<?php if ( ! empty( $archive ) ) : ?>
				<section class="dmi-release-archive">
					<h2>Release archive</h2>

					<?php foreach ( $archive as $release ) : ?>
						<div class="dmi-archive-item">
							<h3><?php echo esc_html( $release['release_id'] ); ?></h3>

							<p>
								<strong>Data through:</strong> <?php echo esc_html( $release['data_through_label'] ); ?><br>
								<strong>Published:</strong> <?php echo esc_html( tcw_dmi_format_date( $release['published_at'] ) ); ?><br>
								<strong>Status:</strong> <?php echo esc_html( ucfirst( $release['status'] ) ); ?><br>
								<strong>Methodology version:</strong> <?php echo esc_html( $release['methodology_version'] ); ?>
							</p>

							<?php if ( ! empty( $release['summary'] ) ) : ?>
								<p><?php echo esc_html( $release['summary'] ); ?></p>
							<?php endif; ?>

							<?php if ( ! empty( $release['spec_urls'] ) && is_array( $release['spec_urls'] ) ) : ?>
								<?php echo tcw_dmi_render_spec_links_table( $release['spec_urls'] ); ?>
							<?php endif; ?>
						</div>
					<?php endforeach; ?>
				</section>
			<?php endif; ?>

		</div>
		<?php

		return ob_get_clean();
	}

	add_shortcode( 'dmi_release_data', 'tcw_dmi_release_data_shortcode' );
}
