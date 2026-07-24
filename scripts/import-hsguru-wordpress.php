<?php

declare(strict_types=1);

function hsguru_import_valid_deck_code(string $value): bool
{
    $value = trim($value);
    return strlen($value) >= 40 && preg_match('/^[A-Za-z0-9+\/=]+$/', $value) === 1;
}

function hsguru_import_deck_title(array $row): string
{
    $deck = trim((string) ($row['Deck'] ?? ''));
    $code = trim((string) ($row['deck_code'] ?? ''));
    if ($deck === '' || $code === '') {
        return '';
    }

    $deck = preg_replace('/^\s*###\s*/u', '', $deck) ?? $deck;
    $codeOffset = strpos($deck, $code);
    if ($codeOffset !== false) {
        $deck = substr($deck, 0, $codeOffset);
    }

    return trim(preg_replace('/\s+/u', ' ', $deck) ?? $deck, " \t\n\r\0\x0B#");
}

function hsguru_import_record(array $row, string $sourceUrl): ?array
{
    $deckCode = trim((string) ($row['deck_code'] ?? ''));
    $title = hsguru_import_deck_title($row);
    if ($title === '' || !hsguru_import_valid_deck_code($deckCode)) {
        return null;
    }

    $wins = 0;
    $losses = 0;
    if (preg_match('/(\d+)\s*-\s*(\d+)/', (string) ($row['Win - Loss'] ?? ''), $matches) === 1) {
        $wins = (int) $matches[1];
        $losses = (int) $matches[2];
    }

    $streamer = trim((string) ($row['Streamer'] ?? ''));

    return [
        'title' => $title,
        'deck_code' => $deckCode,
        'streamer' => $streamer,
        'player' => $streamer,
        'source_url' => $sourceUrl,
        'wins' => $wins,
        'losses' => $losses,
        'games' => $wins + $losses,
        'peak' => trim((string) ($row['Peak'] ?? '')),
        'latest' => trim((string) ($row['Latest'] ?? '')),
        'worst' => trim((string) ($row['Worst'] ?? '')),
        'publish_to_feed' => true,
        'exclude_from_random' => false,
        'generate_kolodahs_image' => true,
        'dedupe_by_deck_code' => true,
    ];
}

function hsguru_import_records(array $rows, string $sourceUrl): array
{
    $recordsByCode = [];
    $invalid = 0;
    foreach ($rows as $row) {
        if (!is_array($row)) {
            $invalid++;
            continue;
        }
        $record = hsguru_import_record($row, $sourceUrl);
        if ($record === null) {
            $invalid++;
            continue;
        }
        $code = $record['deck_code'];
        if (!isset($recordsByCode[$code]) || $record['games'] > $recordsByCode[$code]['games']) {
            $recordsByCode[$code] = $record;
        }
    }

    return [
        'records' => array_values($recordsByCode),
        'invalid' => $invalid,
        'duplicates_in_source' => max(0, count($rows) - $invalid - count($recordsByCode)),
    ];
}

function hsguru_import_existing_deck_ids(string $deckCode): array
{
    global $wpdb;

    $sql = $wpdb->prepare(
        "SELECT DISTINCT p.ID
         FROM {$wpdb->posts} p
         INNER JOIN {$wpdb->postmeta} pm ON pm.post_id = p.ID
         WHERE p.post_type = 'hs_deck'
           AND p.post_status NOT IN ('trash', 'auto-draft')
           AND pm.meta_key = '_deck_code'
           AND TRIM(pm.meta_value) = %s
         ORDER BY p.ID ASC",
        $deckCode
    );

    return array_map('intval', (array) $wpdb->get_col($sql));
}

function hsguru_import_rest_request(string $route, array $payload): array
{
    $request = new WP_REST_Request('POST', $route);
    $request->set_header('content-type', 'application/json');
    $request->set_body(wp_json_encode($payload));
    $response = rest_do_request($request);
    $status = $response->get_status();
    $data = $response->get_data();

    if ($status < 200 || $status >= 300) {
        $message = is_array($data) && isset($data['message']) ? (string) $data['message'] : 'WordPress REST request failed';
        throw new RuntimeException($message . ' (HTTP ' . $status . ')');
    }

    return is_array($data) ? $data : [];
}

function hsguru_import_update_payload(array $record, int $postId): array
{
    $payload = $record;
    unset(
        $payload['title'],
        $payload['publish_to_feed'],
        $payload['dedupe_by_deck_code'],
        $payload['generate_kolodahs_image']
    );

    $existingSource = trim((string) get_post_meta($postId, '_deck_source_url', true));
    $existingHost = strtolower((string) wp_parse_url($existingSource, PHP_URL_HOST));
    if ($existingHost !== '' && !str_ends_with($existingHost, 'hsguru.com')) {
        unset($payload['source_url']);
    }

    return $payload;
}

function hsguru_import_run(array $options): array
{
    $datasetPath = (string) ($options['dataset'] ?? '/srv/hs-data-api/data/datasets/hsguru_streamer_decks_legend_1000.json');
    $wpLoadPath = (string) ($options['wp-load'] ?? '/var/www/koloda/data/www/hs-manacost.ru/wp-load.php');
    $publish = array_key_exists('publish', $options);

    $datasetRaw = @file_get_contents($datasetPath);
    $dataset = is_string($datasetRaw) ? json_decode($datasetRaw, true) : null;
    if (!is_array($dataset)) {
        throw new RuntimeException('HSGuru dataset is missing or invalid: ' . $datasetPath);
    }

    $rows = $dataset['data']['structured']['rows'] ?? [];
    $sourceUrl = (string) ($dataset['data']['fetch_url'] ?? '');
    if (!is_array($rows) || $sourceUrl === '') {
        throw new RuntimeException('HSGuru dataset does not contain rows or fetch_url');
    }

    $_SERVER['REQUEST_URI'] = $_SERVER['REQUEST_URI'] ?? '/';
    $_SERVER['HTTP_HOST'] = $_SERVER['HTTP_HOST'] ?? 'hs-manacost.ru';
    if (!defined('WP_USE_THEMES')) {
        define('WP_USE_THEMES', false);
    }
    require_once $wpLoadPath;

    $userLogin = (string) ($options['user'] ?? getenv('HS_HSGURU_WP_USER') ?: 'ArdasmanLL');
    $user = get_user_by('login', $userLogin);
    if (!$user || !user_can($user, 'import_hs_decks')) {
        throw new RuntimeException('WordPress import user is missing or lacks import_hs_decks: ' . $userLogin);
    }
    wp_set_current_user((int) $user->ID);

    $normalized = hsguru_import_records($rows, $sourceUrl);
    $summary = [
        'mode' => $publish ? 'publish' : 'dry-run',
        'source_rows' => count($rows),
        'valid_unique' => count($normalized['records']),
        'invalid' => $normalized['invalid'],
        'duplicates_in_source' => $normalized['duplicates_in_source'],
        'created' => 0,
        'updated' => 0,
        'existing' => 0,
        'duplicates_already_in_wordpress' => 0,
        'errors' => [],
    ];

    foreach ($normalized['records'] as $record) {
        $existingIds = hsguru_import_existing_deck_ids($record['deck_code']);
        if ($existingIds) {
            $summary['existing']++;
            $summary['duplicates_already_in_wordpress'] += max(0, count($existingIds) - 1);
            if (!$publish) {
                continue;
            }
            try {
                hsguru_import_rest_request(
                    '/manacost/v1/deck-meta/' . $existingIds[0],
                    hsguru_import_update_payload($record, $existingIds[0])
                );
                $summary['updated']++;
            } catch (Throwable $exception) {
                $summary['errors'][] = ['title' => $record['title'], 'message' => $exception->getMessage()];
            }
            continue;
        }

        if (!$publish) {
            $summary['created']++;
            continue;
        }
        try {
            $response = hsguru_import_rest_request('/manacost/v1/decks', $record);
            if (!empty($response['duplicate'])) {
                $summary['existing']++;
                $summary['updated']++;
            } else {
                $summary['created']++;
            }
        } catch (Throwable $exception) {
            $summary['errors'][] = ['title' => $record['title'], 'message' => $exception->getMessage()];
        }
    }

    return $summary;
}

function hsguru_import_main(array $argv): int
{
    $options = getopt('', ['publish', 'dataset:', 'wp-load:', 'user:']);
    $lockPath = '/srv/hs-data-api/data/.hsguru-wordpress-import.lock';
    $lock = fopen($lockPath, 'c');
    if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
        fwrite(STDERR, "HSGuru WordPress import is already running\n");
        return 75;
    }

    try {
        $summary = hsguru_import_run(is_array($options) ? $options : []);
        echo json_encode($summary, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . PHP_EOL;
        return empty($summary['errors']) ? 0 : 1;
    } catch (Throwable $exception) {
        fwrite(STDERR, $exception->getMessage() . PHP_EOL);
        return 1;
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

if (isset($_SERVER['SCRIPT_FILENAME']) && realpath((string) $_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    exit(hsguru_import_main($argv ?? []));
}
