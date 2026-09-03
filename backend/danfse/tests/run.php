<?php

declare(strict_types=1);

use GuilhermeViana\Nfsenacional\Danfse\DanfseGenerator;
use GuilhermeViana\Nfsenacional\Danfse\Formatter;
use GuilhermeViana\Nfsenacional\Danfse\Template\DanfseTemplate;

require dirname(__DIR__) . '/vendor/autoload.php';

function check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$xmlPath = $argv[1] ?? '';
check($xmlPath !== '' && is_file($xmlPath), 'Informe um XML real para o teste.');

$formatter = new Formatter();
check($formatter->formatNbsCode('114093000') === '1.1409.30.00', 'Formato NBS 114093000.');
check($formatter->formatNbsCode('113019000') === '1.1301.90.00', 'Formato NBS 113019000.');
check($formatter->formatTributacaoNacional('170601') === '17.06.01', 'Formato tributacao 170601.');
check($formatter->formatOptionalMoney(null) === '-', 'Dinheiro ausente.');
check($formatter->formatOptionalMoney(0) === 'R$ 0,00', 'Dinheiro zero explicito.');
check($formatter->formatOptionalPercent(null) === '-', 'Percentual ausente.');
check($formatter->formatOptionalPercent(0) === '0,00%', 'Percentual zero explicito.');

$generator = new DanfseGenerator();
$nfse = $generator->parseXml((string) file_get_contents($xmlPath));
$template = new DanfseTemplate();
$data = $template->buildData($nfse);
$html = $generator->generateHtml($nfse);
$templatePath = dirname(__DIR__) . '/src/Danfse/Template/danfse.php';
$templateSource = (string) file_get_contents($templatePath);

check(str_contains($templateSource, '--danfse-border-width: 1pt;'), 'Espessura centralizada em 1pt.');
check(str_contains($templateSource, '--danfse-border-color: #000000;'), 'Cor centralizada em preto.');
check(!preg_match('/0\\.5pt|thin|dashed|1px|0\\.25pt|0\\.3pt/', $templateSource), 'Sem espessuras finas no template.');
check(!preg_match('/height\\s*:\\s*0\\.[0-9]+px/', $templateSource), 'Sem linhas simuladas por altura fracionaria.');

check($data['numero_nfse'] !== '', 'Numero da NFS-e recebido.');
check($data['servico']['codigo_nbs'] !== '', 'NBS formatada na apresentacao.');
check($data['servico']['codigo_trib_nacional'] !== '', 'Tributacao formatada na apresentacao.');
check($data['situacao'] === 'NFS-e regular (Autorizada)', 'Situacao autorizada.');
check(is_array($data['tributacao_ibscbs']), 'Bloco IBS/CBS sempre presente.');
check(str_contains($data['informacoes_complementares'], 'NBS: ' . $data['servico']['codigo_nbs']), 'NBS nas informacoes complementares.');

if ($data['numero_nfse'] === '541') {
    check($data['servico']['codigo_nbs'] === '1.1806.51.00', 'NBS da nota 541.');
    check($data['servico']['codigo_trib_nacional'] === '13.04.01', 'Tributacao da nota 541.');
    check($data['totais']['valor_servico'] === 'R$ 304,00', 'Valor do servico da nota 541.');
    check($data['tributacao_municipal']['issqn_apurado'] === 'R$ 6,08', 'ISSQN da nota 541.');
    check($data['totais']['valor_liquido'] === 'R$ 297,92', 'Valor liquido da nota 541.');
}
check(
    str_starts_with($template->buildQrCodeUrl($data['chave_acesso']), 'https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave='),
    'URL oficial no QR Code.',
);
check(str_contains($html, 'DATA CIENTIFICA'), 'Canhoto inferior.');
check(str_contains($html, 'border-top: var(--danfse-border-width) solid var(--danfse-border-color);'), 'Canhoto com borda vetorial.');
check(!str_contains($html, 'letter-spacing: 1'), 'Sem espacamento artificial de letras.');

fwrite(STDOUT, "OK: testes DANFSe concluídos.\n");
