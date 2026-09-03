<?php

namespace GuilhermeViana\Nfsenacional\Danfse\Template;

use BaconQrCode\Renderer\Image\SvgImageBackEnd;
use BaconQrCode\Renderer\ImageRenderer;
use BaconQrCode\Renderer\RendererStyle\RendererStyle;
use BaconQrCode\Writer;
use GuilhermeViana\Nfsenacional\Danfse\Config\DanfseConfig;
use GuilhermeViana\Nfsenacional\Danfse\Dto\NFSe;
use GuilhermeViana\Nfsenacional\Danfse\Enums\OpSimpNac;
use GuilhermeViana\Nfsenacional\Danfse\Enums\RegApTribSN;
use GuilhermeViana\Nfsenacional\Danfse\Enums\RegEspTrib;
use GuilhermeViana\Nfsenacional\Danfse\Enums\TpRetISSQN;
use GuilhermeViana\Nfsenacional\Danfse\Enums\TribISSQN;
use GuilhermeViana\Nfsenacional\Danfse\Data\Municipios;
use GuilhermeViana\Nfsenacional\Danfse\Formatter;

/**
 * Constrói o array de dados para o template e gera o QR Code.
 */
class DanfseTemplate
{
    private Formatter $fmt;

    public function __construct()
    {
        $this->fmt = new Formatter();
    }

    /**
     * Renderiza o template e retorna o HTML completo
     */
    public function render(NFSe $nfse, DanfseConfig $config): string
    {
        $data = $this->buildData($nfse);
        $hasSubstTag = (string) ($data['nfse_subst_chave'] ?? '') !== '';
        $resolvedWatermarkStatus = $config->watermarkStatus ?? ($hasSubstTag ? 'substituida' : null);
        $data['watermark_status'] = $resolvedWatermarkStatus;
        $data['watermark_text'] = $this->resolveWatermarkText((string) ($resolvedWatermarkStatus ?? ''));
        $logo = $config->logoDataUri;
        $municipality = $config->municipality;
        $qrCode = $this->generateQrCode($data['chave_acesso']);
        $fontFacesCss = $this->buildFontFacesCss();
        array_walk_recursive($data, fn(&$v) => $v = is_string($v) ? htmlspecialchars($v, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') : $v);

        $templatePath = __DIR__ . '/danfse.php';

        ob_start();
        include $templatePath;
        return ob_get_clean();
    }

    private function resolveWatermarkText(string $status): ?string
    {
        return match ($status) {
            'cancelada' => 'CANCELADA',
            'substituida' => 'SUBSTITUÍDA',
            default => null,
        };
    }

    private function buildFontFacesCss(): string
    {
        $rootPath = dirname(__DIR__, 4);
        $fontDir = $rootPath . '/assets/fonts/ttf';

        $rules = [];
        $rules[] = $this->fontFaceRule('Microsoft Sans Serif', $fontDir . '/ms-sans-serif.ttf', 'normal', 'normal');
        $rules[] = $this->fontFaceRule('Arial', $fontDir . '/arial.ttf', 'normal', 'normal');
        $rules[] = $this->fontFaceRule('Arial', $fontDir . '/arial-bold.ttf', 'normal', 'bold');

        return implode("\n", array_filter($rules));
    }

    private function fontFaceRule(string $family, string $filePath, string $style, string $weight): string
    {
        if (!is_file($filePath) || !is_readable($filePath)) {
            return '';
        }

        $fontData = file_get_contents($filePath);
        if ($fontData === false || $fontData === '') {
            return '';
        }

        $base64 = base64_encode($fontData);

        return sprintf(
            "@font-face {\n"
            . "  font-family: '%s';\n"
            . "  font-style: %s;\n"
            . "  font-weight: %s;\n"
            . "  src: url('data:font/ttf;base64,%s') format('truetype');\n"
            . "}\n",
            $family,
            $style,
            $weight,
            $base64,
        );
    }

    /**
     * Constrói o array de dados para o template a partir dos DTOs
     */
    public function buildData(NFSe $nfse): array
    {
        $inf = $nfse->infNFSe;
        $dps = $inf?->DPS;
        $infDps = $dps?->infDPS;
        $prest = $infDps?->prest;
        $regTrib = $prest?->regTrib;
        $emit = $inf?->emit;
        $enderEmit = $emit?->enderNac;
        $toma = $infDps?->toma;
        $endToma = $toma?->end;
        $interm = $infDps?->interm;
        $endInterm = $interm?->end;
        $serv = $infDps?->serv;
        $locPrest = $serv?->locPrest;
        $cServ = $serv?->cServ;
        $valores = $infDps?->valores;
        $vServPrest = $valores?->vServPrest;
        $trib = $valores?->trib;
        $tribMun = $trib?->tribMun;
        $tribFed = $trib?->tribFed;
        $totTrib = $trib?->totTrib;
        $totTribPercent = $totTrib?->pTotTrib;
        $totTribValues = is_array($totTrib?->vTotTrib ?? null) ? $totTrib->vTotTrib : null;
        $valoresNfse = $inf?->valores;
        $ibscbs = $inf?->IBSCBS;
        $ibscbsValores = $ibscbs?->valores;
        $totCIBS = $ibscbs?->totCIBS;
        $dpsIbscbs = $infDps?->IBSCBS;
        $dest = $dpsIbscbs?->dest;
        $endDest = $dest?->end;
        $imovel = $dpsIbscbs?->imovel;
        $obra = $serv?->obra;
        $atvEvento = $serv?->atvEvento;
        $infoCompl = $serv?->infoCompl;
        $chaveSubst = trim((string) ($infDps?->subst?->chSubstda ?? ''));

        // Chave de acesso (remove prefixo "NFS")
        $id = $inf?->Id ?? '';
        $chaveAcesso = str_starts_with($id, 'NFS') ? substr($id, 3) : $id;

        // Endereço emitente
        $enderecoEmit = $this->fmt->formatAddress([
            $enderEmit?->xLgr ?? '',
            $enderEmit?->nro ?? '',
            $enderEmit?->xCpl ?? '',
            $enderEmit?->xBairro ?? '',
            ($inf?->xLocEmi ?? '') !== '' ? $inf->xLocEmi . (($enderEmit?->UF ?? '') !== '' ? ' / ' . $enderEmit->UF : '') : '',
            ($enderEmit?->CEP ?? '') !== '' ? $this->fmt->cep($enderEmit->CEP) : '',
        ]);

        $municipioEmit = '';
        if (($inf?->xLocEmi ?? '') !== '' && ($enderEmit?->UF ?? '') !== '') {
            $municipioEmit = ($inf->xLocEmi) . ' / ' . $enderEmit->UF;
        }

        // Endereço tomador
        $enderecoToma = $this->fmt->formatAddress([
            $endToma?->xLgr ?? '',
            $endToma?->nro ?? '',
            $endToma?->xCpl ?? '',
            $endToma?->xBairro ?? '',
            ($endToma?->endNac?->cMun ?? '') !== '' ? Municipios::lookup($endToma->endNac->cMun) : ($endToma?->endExt?->xCidade ?? ''),
            ($endToma?->endNac?->CEP ?? '') !== '' ? $this->fmt->cep($endToma->endNac->CEP) : ($endToma?->endExt?->cEndPost ?? ''),
        ]);

        $cepToma = $endToma?->endNac?->CEP ?? '';
        $tomadorCodigoIbgeCep = '-';
        $tomadorIbge = $endToma?->endNac?->cMun ?? '';
        $tomadorPostal = $cepToma !== ''
            ? $this->fmt->cep($cepToma)
            : (($endToma?->endExt?->cEndPost ?? '') !== '' ? $endToma->endExt->cEndPost : '');
        if ($tomadorIbge !== '' || $tomadorPostal !== '') {
            $tomadorCodigoIbgeCep = trim($tomadorIbge . ' / ' . $tomadorPostal, ' /');
        }

        $tomadorMunicipio = '-';
        if (($endToma?->endNac?->cMun ?? '') !== '') {
            $tomadorMunicipio = Municipios::lookup($endToma->endNac->cMun);
        } elseif (($endToma?->endExt?->xCidade ?? '') !== '') {
            $tomadorMunicipio = $endToma->endExt->xCidade;
        }

        // Endereço intermediário
        $enderecoInterm = $this->fmt->formatAddress([
            $endInterm?->xLgr ?? '',
            $endInterm?->nro ?? '',
            $endInterm?->xCpl ?? '',
            $endInterm?->xBairro ?? '',
            ($endInterm?->endNac?->cMun ?? '') !== '' ? Municipios::lookup($endInterm->endNac->cMun) : ($endInterm?->endExt?->xCidade ?? ''),
            ($endInterm?->endNac?->CEP ?? '') !== '' ? $this->fmt->cep($endInterm->endNac->CEP) : ($endInterm?->endExt?->cEndPost ?? ''),
        ]);

        $cepInterm = $endInterm?->endNac?->CEP ?? '';
        $intermediarioCodigoIbgeCep = '-';
        $intermediarioIbge = $endInterm?->endNac?->cMun ?? '';
        $intermediarioPostal = $cepInterm !== ''
            ? $this->fmt->cep($cepInterm)
            : (($endInterm?->endExt?->cEndPost ?? '') !== '' ? $endInterm->endExt->cEndPost : '');
        if ($intermediarioIbge !== '' || $intermediarioPostal !== '') {
            $intermediarioCodigoIbgeCep = trim($intermediarioIbge . ' / ' . $intermediarioPostal, ' /');
        }

        $intermediarioMunicipio = '-';
        if (($endInterm?->endNac?->cMun ?? '') !== '') {
            $intermediarioMunicipio = Municipios::lookup($endInterm->endNac->cMun);
        } elseif (($endInterm?->endExt?->xCidade ?? '') !== '') {
            $intermediarioMunicipio = $endInterm->endExt->xCidade;
        }

        $emitenteCodigoIbgeCep = '-';
        $emitenteIbge = $enderEmit?->cMun ?? '';
        $emitentePostal = ($enderEmit?->CEP ?? '') !== '' ? $this->fmt->cep($enderEmit->CEP) : '';
        if ($emitenteIbge !== '' || $emitentePostal !== '') {
            $emitenteCodigoIbgeCep = trim($emitenteIbge . ' / ' . $emitentePostal, ' /');
        }

        // Endereço destinatário
        $enderecoDest = $this->fmt->formatAddress([
            $endDest?->xLgr ?? '',
            $endDest?->nro ?? '',
            $endDest?->xCpl ?? '',
            $endDest?->xBairro ?? '',
            ($endDest?->endNac?->cMun ?? '') !== '' ? Municipios::lookup($endDest->endNac->cMun) : ($endDest?->endExt?->xCidade ?? ''),
            ($endDest?->endNac?->CEP ?? '') !== '' ? $this->fmt->cep($endDest->endNac->CEP) : ($endDest?->endExt?->cEndPost ?? ''),
        ]);

        $destMunicipio = '-';
        if (($endDest?->endNac?->cMun ?? '') !== '') {
            $destMunicipio = Municipios::lookup($endDest->endNac->cMun);
        } elseif (($endDest?->endExt?->xCidade ?? '') !== '') {
            $destMunicipio = $endDest->endExt->xCidade;
        }

        $destCodigoIbge = $endDest?->endNac?->cMun ?? '';
        $destPostalCode = ($endDest?->endNac?->CEP ?? '') !== ''
            ? $this->fmt->cep($endDest->endNac->CEP)
            : (($endDest?->endExt?->cEndPost ?? '') !== '' ? $endDest->endExt->cEndPost : '');

        $destCodigoIbgeCep = '-';
        if ($destCodigoIbge !== '' || $destPostalCode !== '') {
            $destCodigoIbgeCep = trim($destCodigoIbge . ' / ' . $destPostalCode, ' /');
        }

        // Totais aproximados dos tributos (percentual tem prioridade sobre valor)
        $totTribFed = $totTribPercent?->pTotTribFed
            ? $totTribPercent->pTotTribFed . '%'
            : (($totTribValues['vTotTribFed'] ?? '') !== '' ? $this->fmt->currency((string) $totTribValues['vTotTribFed']) : '-');
        $totTribEst = $totTribPercent?->pTotTribEst
            ? $totTribPercent->pTotTribEst . '%'
            : (($totTribValues['vTotTribEst'] ?? '') !== '' ? $this->fmt->currency((string) $totTribValues['vTotTribEst']) : '-');
        $totTribMun = $totTribPercent?->pTotTribMun
            ? $totTribPercent->pTotTribMun . '%'
            : (($totTribValues['vTotTribMun'] ?? '') !== '' ? $this->fmt->currency((string) $totTribValues['vTotTribMun']) : '-');

        // Texto dos Totais Aproximados dos Tributos (Lei nº 12.741/2012) para as
        // Informações Complementares. Só é gerado quando há algum valor/percentual no XML.
        $totaisAproxTributos = '';
        if ($totTribFed !== '-' || $totTribEst !== '-' || $totTribMun !== '-') {
            $totaisAproxTributos = sprintf(
                'Totais Aproximados dos Tributos cfe. Lei nº 12.741/2012: Federais: %s; Estaduais: %s; Municipais: %s;',
                $totTribFed,
                $totTribEst,
                $totTribMun,
            );
        }

        // Informações Complementares: união de todos os campos, na ordem definida
        // pelo layout do DANFSe Nacional, separados por " | ". Limitado a 1997
        // caracteres (a linha de Totais Aproximados dos Tributos é fixa e não conta
        // nesse limite, pois é renderizada à parte).
        $itemPed = $infoCompl?->gItemPed?->xItemPed ?? '';
        $itemPedTexto = is_array($itemPed) ? implode(', ', $itemPed) : trim((string) $itemPed);
        $nbsOriginal = trim((string) ($cServ?->cNBS ?? ''));
        $nbsFormatado = $this->fmt->formatNbsCode($nbsOriginal);
        $nbsDescricao = trim((string) ($inf?->xNBS ?? ''));
        foreach ([$nbsOriginal, $nbsFormatado] as $prefixoNbs) {
            if ($prefixoNbs !== '' && $prefixoNbs !== '-') {
                $nbsDescricao = preg_replace(
                    '/^' . preg_quote($prefixoNbs, '/') . '\s*[-:]*\s*/u',
                    '',
                    $nbsDescricao,
                ) ?? $nbsDescricao;
            }
        }
        $nbsComplementar = $nbsFormatado !== '-'
            ? $nbsFormatado . ($nbsDescricao !== '' ? ' - ' . $nbsDescricao : '')
            : '';

        $infoComplPartes = [
            'Inf. Cont.' => trim($infoCompl?->xInfComp ?? ''),
            'NBS' => $nbsComplementar,
            'NFS-e Subst.' => $chaveSubst,
            'Doc. Ref.' => trim($infoCompl?->docRef ?? ''),
            'Cod. Obra' => trim($obra?->cObra ?? ''),
            'Insc. Imob.' => trim($imovel?->inscImobFisc ?? ''),
            'Cod. Evt.' => trim($atvEvento?->idAtvEvt ?? ''),
            'Doc. Tec.' => trim($infoCompl?->idDocTec ?? ''),
            'Núm. Ped.' => trim($infoCompl?->xPed ?? ''),
            'Item Ped.' => $itemPedTexto,
            'Inf. A. T. Mun.' => trim($inf?->xOutInf ?? ''),
        ];

        // xInfComp is already formatted by the issuer and must be preserved
        // verbatim; only the other optional XML fields receive a label.
        $informacoesComplementaresPartes = [];
        if ($infoComplPartes['Inf. Cont.'] !== '') {
            $informacoesComplementaresPartes[] = $infoComplPartes['Inf. Cont.'];
        }
        foreach ($infoComplPartes as $label => $valor) {
            if ($label !== 'Inf. Cont.' && $valor !== '') {
                $informacoesComplementaresPartes[] = $label . ': ' . $valor;
            }
        }
        $informacoesComplementares = implode(' | ', $informacoesComplementaresPartes);
        $informacoesComplementares = $this->fmt->limit($informacoesComplementares, 1997);

        return [
            'chave_acesso' => $chaveAcesso,
            'numero_nfse' => $inf?->nNFSe ?? '-',
            'competencia' => $this->fmt->date($infDps?->dCompet ?? ''),
            'emissao_nfse' => $this->fmt->dateTime($inf?->dhProc ?? ''),
            'numero_dps' => $infDps?->nDPS ?? '-',
            'serie_dps' => $infDps?->serie ?? '-',
            'emissao_dps' => $this->fmt->dateTime($infDps?->dhEmi ?? ''),
            'ambiente' => (int) ($infDps?->tpAmb ?? 1),
            'emitente_nfse' => match ((string) ($infDps?->tpEmit ?? '')) {
                '1' => 'Prestador',
                '2' => 'Tomador',
                '3' => 'Intermediário',
                default => '-',
            },
            'situacao' => match ((string) ($inf?->cStat ?? '')) {
                '100', '107' => 'NFS-e regular (Autorizada)',
                '' => '-',
                default => 'Situação ' . (string) $inf->cStat,
            },
            'finalidade' => match ((string) ($infDps?->IBSCBS?->finNFSe ?? '')) {
                '0' => 'NFS-e regular',
                '1' => 'NFS-e de crédito',
                '2' => 'NFS-e de débito',
                default => '-',
            },

            'emitente' => [
                'nome' => $emit?->xNome ?? '-',
                'cnpj_cpf' => $this->fmt->cnpjCpf($emit?->documento() ?? ''),
                'im' => '-',
                'telefone' => $this->fmt->phone($emit?->fone ?? ''),
                'email' => strtolower($emit?->email ?? ''),
                'endereco' => $enderecoEmit ?: '-',
                'municipio' => $municipioEmit ?: '-',
                'cep' => $emitenteCodigoIbgeCep,
                'simples_nacional' => OpSimpNac::labelFor($regTrib?->opSimpNac ?? ''),
                'regime_sn' => RegApTribSN::labelFor($regTrib?->regApTribSN ?? ''),
            ],

            'tomador' => $toma !== null ? [
                'nome' => $toma->xNome ?: '-',
                'cnpj_cpf' => $this->fmt->cnpjCpf($toma->documento()),
                'im' => $toma->IM ?: '-',
                'telefone' => $this->fmt->phone($toma->fone),
                'email' => strtolower($toma->email),
                'endereco' => $enderecoToma ?: '-',
                'municipio' => $tomadorMunicipio,
                'cep' => $tomadorCodigoIbgeCep,
            ] : null,

            'intermediario' => $interm !== null ? [
                'nome' => $interm->xNome ?: '-',
                'cnpj_cpf' => $this->fmt->cnpjCpf($interm->documento()),
                'im' => $interm->IMPrestMun ?: '-',
                'telefone' => $this->fmt->phone($interm->fone),
                'email' => strtolower($interm->email),
                'endereco' => $enderecoInterm ?: '-',
                'municipio' => $intermediarioMunicipio,
                'cep' => $intermediarioCodigoIbgeCep,
            ] : null,

            // Destinatário da Operação (grupo IBSCBS/dest).
            // null = não identificado; array = identificado.
            'destinatario' => $dest !== null ? [
                'nome' => $dest->xNome ?: '-',
                'cnpj_cpf' => $this->fmt->cnpjCpf($dest->documento() ?: '-'),
                'telefone' => $this->fmt->phone($dest->fone ?: '-'),
                'email' => trim((string) $dest->email) !== '' ? strtolower($dest->email) : '-',
                'endereco' => $enderecoDest ?: '-',
                'municipio' => $destMunicipio,
                'cep' => $destCodigoIbgeCep,
            ] : null,

            'servico' => [
                'codigo_trib_nacional' => $this->fmt->formatTributacaoNacional($cServ?->cTribNac ?? ''),
                'desc_trib_nacional' => $this->fmt->limit(trim($inf?->xTribNac ?? ''), 40),
                'codigo_trib_municipal' => $cServ?->cTribMun ?? '-',
                'codigo_trib_nac_mun' => $this->fmt->codTribNacMun($cServ?->cTribNac ?? '', $cServ?->cTribMun ?? ''),
                'codigo_nbs' => $nbsFormatado,
                'desc_trib_municipal' => $this->fmt->limit(trim($inf?->xTribMun ?? ''), 60),
                'desc_trib_nac_mun' => trim($inf?->xTribMun ?? '') !== ''
                    ? trim($inf->xTribMun)
                    : (trim($inf?->xTribNac ?? '') !== '' ? trim($inf->xTribNac) : '-'),
                'local_prestacao' => $locPrest?->cLocPrestacao ? Municipios::lookup($locPrest->cLocPrestacao) : ($inf?->xLocPrestacao ?? '-'),
                'local_prestacao_pais' => $locPrest?->cLocPrestacao
                    ? Municipios::lookup($locPrest->cLocPrestacao)
                    : (($locPrest?->cPaisPrestacao ?? '') !== ''
                        ? $locPrest->cPaisPrestacao
                        : (($inf?->xLocPrestacao ?? '') !== '' ? $inf->xLocPrestacao : '-')),
                'pais_prestacao' => $locPrest?->cPaisPrestacao ?? '-',
                'descricao' => $cServ?->xDescServ ?? '-',
            ],

            'tributacao_municipal' => $tribMun !== null ? [
                'tributacao_issqn' => TribISSQN::labelFor($tribMun->tribISSQN ?? ''),
                'municipio_incidencia' => $inf?->cLocIncid
                    ? Municipios::lookup($inf->cLocIncid)
                    : (($inf?->xLocIncid ?? '') !== '' ? $inf->xLocIncid : '-'),
                'regime_especial' => RegEspTrib::labelFor($regTrib?->regEspTrib ?? ''),
                'bc_issqn' => ($tribMun->vBC ?? '') !== ''
                    ? $this->fmt->currency($tribMun->vBC)
                    : ((($valoresNfse?->vBC ?? '') !== '') ? $this->fmt->currency($valoresNfse->vBC) : '-'),
                'aliquota' => ($tribMun->pAliq ?? '') !== ''
                    ? $this->fmt->formatOptionalPercent($tribMun->pAliq)
                    : $this->fmt->formatOptionalPercent($valoresNfse?->pAliqAplic ?? null),
                'retencao_issqn' => TpRetISSQN::labelFor($tribMun->tpRetISSQN ?? ''),
                'issqn_apurado' => ($tribMun->vISSQN ?? '') !== ''
                    ? $this->fmt->currency($tribMun->vISSQN)
                    : ((($valoresNfse?->vISSQN ?? '') !== '') ? $this->fmt->currency($valoresNfse->vISSQN) : '-'),
            ] : null,

            'tributacao_federal' => [
                'irrf' => $this->fmt->formatOptionalMoney($tribFed?->vRetIRRF ?? null),
                'cp' => $this->fmt->formatOptionalMoney($tribFed?->vRetCP ?? null),
                'csll' => $this->fmt->formatOptionalMoney($tribFed?->vRetCSLL ?? null),
                'contrib_sociais' => $this->fmt->formatOptionalMoney($tribFed?->vRetCSLL ?? null),
                'desc_contrib_sociais' => $this->labelForTpRetPisCofins($tribFed?->piscofins?->tpRetPisCofins ?? ''),
                'pis' => $this->fmt->formatOptionalMoney(($tribFed?->piscofins?->vPis ?? '') !== '' ? $tribFed->piscofins->vPis : ($tribFed?->vPis ?? null)),
                'cofins' => $this->fmt->formatOptionalMoney(($tribFed?->piscofins?->vCofins ?? '') !== '' ? $tribFed->piscofins->vCofins : ($tribFed?->vCofins ?? null)),
            ],

            'totais' => [
                'valor_servico' => $this->fmt->currency($vServPrest?->vServ ?? ''),
                'desconto_condicionado' => $this->fmt->formatOptionalMoney($tribMun?->vDescCond ?? null),
                'desconto_incondicionado' => $this->fmt->formatOptionalMoney($tribMun?->vDescIncond ?? null),
                'issqn_retido' => (($tribMun?->vISSQN ?? '') !== '' || (($valoresNfse?->vISSQN ?? '') !== '')) && ($tribMun?->tpRetISSQN ?? '1') !== '1'
                    ? $this->fmt->currency(($tribMun?->vISSQN ?? '') !== '' ? $tribMun->vISSQN : $valoresNfse->vISSQN)
                    : '-',
                'total_retencoes' => ($valoresNfse?->vTotalRet ?? '') !== ''
                    ? $this->fmt->currency($valoresNfse->vTotalRet)
                    : '-',
                'retencoes_federais' => $this->sumCurrency(
                    $tribFed?->vRetIRRF ?? '',
                    $tribFed?->vRetCP ?? '',
                    $tribFed?->vRetCSLL ?? '',
                ),
                'valor_liquido' => $this->fmt->currency($valoresNfse?->vLiq ?? ''),
                'total_ibscbs' => $this->sumCurrency(
                    $totCIBS?->gIBS?->vIBSTot ?? '',
                    $totCIBS?->gCBS?->vCBS ?? '',
                ),
                'valor_liquido_ibscbs' => ($totCIBS?->vTotNF ?? '') !== ''
                    ? $this->fmt->currency($totCIBS->vTotNF)
                    : '-',
            ],

            'totais_tributos' => [
                'federais' => $totTribFed,
                'estaduais' => $totTribEst,
                'municipais' => $totTribMun,
            ],
            'totais_aprox_tributos' => $totaisAproxTributos,

            'municipio_emissao' => ($inf?->xLocEmi ?? '') !== '' && ($cServ?->cTribNac ?? '') !== '99'
                ? 'Município: ' . $inf->xLocEmi . (($enderEmit?->UF ?? '') !== '' ? ' / ' . $enderEmit->UF : '')
                : '',
            'ambiente_gerador' => $this->labelForAmbGer($inf?->ambGer ?? ''),
            'tipo_ambiente' => $this->labelForTpAmb((string) ($infDps?->tpAmb ?? '')),

            'tributacao_ibscbs' => [
                'cst' => $this->fmt->formatOptionalText($dpsIbscbs?->valores?->trib?->gIBSCBS?->CST ?? null),
                'class_trib' => $this->fmt->formatOptionalText($dpsIbscbs?->valores?->trib?->gIBSCBS?->cClassTrib ?? null),
                'ind_op' => $this->fmt->formatOptionalText($dpsIbscbs?->cIndOp ?? null),
                'cod_ibge_incidencia' => $this->fmt->formatOptionalText($ibscbs?->cLocalidadeIncid ?? null),
                'municipio_incidencia_uf' => ($ibscbs?->cLocalidadeIncid ?? '') !== ''
                    ? Municipios::lookup($ibscbs->cLocalidadeIncid)
                    : $this->fmt->formatOptionalText($ibscbs?->xLocalidadeIncid ?? null),
                'exclusoes_reducoes' => $this->fmt->formatOptionalMoney($ibscbsValores?->vCalcReeRepRes ?? null),
                'vbc' => $this->fmt->formatOptionalMoney($ibscbsValores?->vBC ?? null),
                'p_red_aliq_uf' => $this->fmt->formatOptionalPercent($ibscbsValores?->uf?->pRedAliqUF ?? null),
                'p_red_aliq_mun' => $this->fmt->formatOptionalPercent($ibscbsValores?->mun?->pRedAliqMun ?? null),
                'p_red_aliq_cbs' => $this->fmt->formatOptionalPercent($ibscbsValores?->fed?->pRedAliqCBS ?? null),
                'p_ibs_uf' => $this->fmt->formatOptionalPercent($ibscbsValores?->uf?->pIBSUF ?? null),
                'p_ibs_mun' => $this->fmt->formatOptionalPercent($ibscbsValores?->mun?->pIBSMun ?? null),
                'p_aliq_efet_mun' => $this->fmt->formatOptionalPercent($ibscbsValores?->mun?->pAliqEfetMun ?? null),
                'v_ibs_mun' => $this->fmt->formatOptionalMoney($totCIBS?->gIBS?->gIBSMunTot?->vIBSMun ?? null),
                'p_aliq_efet_uf' => $this->fmt->formatOptionalPercent($ibscbsValores?->uf?->pAliqEfetUF ?? null),
                'v_ibs_uf' => $this->fmt->formatOptionalMoney($totCIBS?->gIBS?->gIBSUFTot?->vIBSUF ?? null),
                'v_ibs_tot' => $this->fmt->formatOptionalMoney($totCIBS?->gIBS?->vIBSTot ?? null),
                'p_cbs' => $this->fmt->formatOptionalPercent($ibscbsValores?->fed?->pCBS ?? null),
                'p_aliq_efet_cbs' => $this->fmt->formatOptionalPercent($ibscbsValores?->fed?->pAliqEfetCBS ?? null),
                'v_cbs' => $this->fmt->formatOptionalMoney($totCIBS?->gCBS?->vCBS ?? null),
            ],

            'nbs' => $nbsFormatado,
            'nfse_subst_chave' => $chaveSubst,
            'informacoes_complementares' => $informacoesComplementares,
        ];
    }

    /**
     * Soma valores monetários e retorna formatado, ou '-' se todos forem vazios.
     */
    private function sumCurrency(string ...$values): string
    {
        $sum = 0.0;
        $hasValue = false;
        foreach ($values as $v) {
            if ($v !== '') {
                $sum += (float) $v;
                $hasValue = true;
            }
        }
        return $hasValue ? $this->fmt->currency((string) $sum) : '-';
    }

    private function labelForAmbGer(string $ambGer): string
    {
        return match (trim($ambGer)) {
            '1' => '1 - Contribuinte',
            '2' => '2 - Fisco',
            '3' => '3 - Contribuinte c/ Fisco',
            '4' => '4 - Terceiro',
            default => $ambGer !== '' ? $ambGer : '-',
        };
    }

    private function labelForTpAmb(string $tpAmb): string
    {
        return match (trim($tpAmb)) {
            '1' => '1 - Produção',
            '2' => '2 - Homologação',
            default => $tpAmb !== '' ? $tpAmb : '-',
        };
    }

    private function labelForTpRetPisCofins(string $tpRetPisCofins): string
    {
        return match (trim($tpRetPisCofins)) {
            '0' => '0 - PIS/COFINS/CSLL Não Retidos',
            '1' => '1 - PIS/COFINS Retido',
            '2' => '2 - PIS/COFINS Não Retido',
            '3' => '3 - PIS/COFINS/CSLL Retidos',
            '4' => '4 - PIS/COFINS Retidos, CSLL Não Retido',
            '5' => '5 - PIS Retido, COFINS/CSLL Não Retido',
            '6' => '6 - COFINS Retido, PIS/CSLL Não Retido',
            '7' => '7 - PIS Não Retido, COFINS/CSLL Retidos',
            '8' => '8 - PIS/COFINS Não Retidos, CSLL Retido',
            '9' => '9 - COFINS Não Retido, PIS/CSLL Retidos',
            default => '-',
        };
    }

    /**
     * Gera QR Code como data URI PNG
     */
    private function generateQrCode(string $chaveAcesso): string
    {
        $url = $this->buildQrCodeUrl($chaveAcesso);

        $renderer = new ImageRenderer(
            new RendererStyle(200),
            new SvgImageBackEnd(),
        );
        $writer = new Writer($renderer);
        $svg = $writer->writeString($url);

        // Retorna como SVG embutido em data URI
        return 'data:image/svg+xml;base64,' . base64_encode($svg);
    }

    public function buildQrCodeUrl(string $chaveAcesso): string
    {
        $chaveAcesso = preg_replace('/\s+/', '', $chaveAcesso) ?? '';
        return "https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave={$chaveAcesso}";
    }
}
