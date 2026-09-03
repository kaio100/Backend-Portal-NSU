<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use GuilhermeViana\Nfsenacional\Danfse\DanfseGenerator;

if ($argc < 3 || $argc > 4) {
    fwrite(STDERR, "Uso: php generate.php <xml> <pdf> [watermark]\n");
    exit(64);
}

$xmlPath = $argv[1];
$pdfPath = $argv[2];
$watermark = $argc === 4 ? trim($argv[3]) : '';

if (!is_file($xmlPath) || !is_readable($xmlPath)) {
    fwrite(STDERR, "Arquivo XML nao encontrado ou sem permissao de leitura.\n");
    exit(65);
}

$xml = file_get_contents($xmlPath);
if ($xml === false || trim($xml) === '') {
    fwrite(STDERR, "Arquivo XML vazio ou ilegivel.\n");
    exit(65);
}

try {
    $generator = new DanfseGenerator();
    $generator->generate(
        $xmlPath,
        [
            'output' => 'file',
            'outputPath' => $pdfPath,
            'watermark' => $watermark !== '' ? $watermark : null,
        ],
    );
} catch (Throwable $exception) {
    fwrite(STDERR, $exception->getMessage() . "\n");
    exit(70);
}

if (!is_file($pdfPath) || filesize($pdfPath) === 0) {
    fwrite(STDERR, "A biblioteca nao produziu um PDF valido.\n");
    exit(70);
}

exit(0);
