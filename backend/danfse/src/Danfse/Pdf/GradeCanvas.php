<?php

declare(strict_types=1);

namespace GuilhermeViana\Nfsenacional\Danfse\Pdf;

use Dompdf\Adapter\CPDF;

/**
 * Canvas do Dompdf que separa a grade de linhas do DANFSe do conteudo.
 *
 * O template pinta todas as linhas do layout (moldura, divisorias e recibo)
 * com COR_GRADE. As bordas continuam no CSS com a mesma espessura, entao o
 * Dompdf calcula o layout e a geometria de cada linha exatamente como antes;
 * so que aqui, em vez de desenhar na hora (antes dos fundos, textos, imagens
 * e carimbos que vem depois na mesma pagina), o traco e guardado com a
 * posicao, a espessura e o recorte de canto que o Dompdf usaria.
 *
 * desenharGrade() e chamado pelo callback "end_page_render", depois que todo o
 * conteudo da pagina foi renderizado: a grade e desenhada por ultimo, em
 * preto e opacidade total. Segmentos colineares das tabelas com borda
 * colapsada (o Dompdf desenha uma linha por celula, sobrepostas em 1pt) sao
 * unidos num traco unico, sem alterar a extensao total.
 *
 * Se este canvas nao estiver ativo, o Dompdf desenha as linhas normalmente em
 * COR_GRADE, que e visualmente preta.
 */
final class GradeCanvas extends CPDF
{
    public const COR_GRADE = '#010203';

    private const COR_TRACO = [0.0, 0.0, 0.0, 'alpha' => 1.0, 'hex' => '#000000'];

    /** Tolerancia, em pontos, para considerar dois segmentos colineares/contiguos. */
    private const TOLERANCIA = 0.01;

    /** @var array<int, list<array<string, mixed>>> tracos guardados por pagina */
    private array $grade = [];

    /** @var list<array<string, mixed>> recortes ativos, na ordem em que foram abertos */
    private array $recortes = [];

    public function line($x1, $y1, $x2, $y2, $color, $width, $style = [], $cap = 'butt')
    {
        if ($this->ehGrade($color)) {
            $this->guardar(['tipo' => 'linha', 'pontos' => [(float) $x1, (float) $y1, (float) $x2, (float) $y2], 'largura' => (float) $width, 'estilo' => $style, 'ponta' => $cap]);
            return;
        }
        parent::line($x1, $y1, $x2, $y2, $color, $width, $style, $cap);
    }

    public function rectangle($x1, $y1, $w, $h, $color, $width, $style = [], $cap = 'butt')
    {
        if ($this->ehGrade($color)) {
            $this->guardar(['tipo' => 'retangulo', 'pontos' => [(float) $x1, (float) $y1, (float) $w, (float) $h], 'largura' => (float) $width, 'estilo' => $style, 'ponta' => $cap]);
            return;
        }
        parent::rectangle($x1, $y1, $w, $h, $color, $width, $style, $cap);
    }

    public function arc($x, $y, $r1, $r2, $astart, $aend, $color, $width, $style = [], $cap = 'butt')
    {
        if ($this->ehGrade($color)) {
            $this->guardar(['tipo' => 'arco', 'pontos' => [$x, $y, $r1, $r2, $astart, $aend], 'largura' => (float) $width, 'estilo' => $style, 'ponta' => $cap]);
            return;
        }
        parent::arc($x, $y, $r1, $r2, $astart, $aend, $color, $width, $style, $cap);
    }

    public function polygon($points, $color, $width = null, $style = [], $fill = false)
    {
        if ($this->ehGrade($color)) {
            $this->guardar(['tipo' => 'poligono', 'pontos' => $points, 'largura' => $width, 'estilo' => $style, 'preenchido' => $fill]);
            return;
        }
        parent::polygon($points, $color, $width, $style, $fill);
    }

    public function filled_rectangle($x1, $y1, $w, $h, $color)
    {
        if ($this->ehGrade($color)) {
            $this->guardar(['tipo' => 'retangulo_cheio', 'pontos' => [(float) $x1, (float) $y1, (float) $w, (float) $h]]);
            return;
        }
        parent::filled_rectangle($x1, $y1, $w, $h, $color);
    }

    public function clipping_rectangle($x1, $y1, $w, $h)
    {
        $this->recortes[] = ['tipo' => 'retangulo', 'args' => [$x1, $y1, $w, $h]];
        parent::clipping_rectangle($x1, $y1, $w, $h);
    }

    public function clipping_roundrectangle($x1, $y1, $w, $h, $rTL, $rTR, $rBR, $rBL)
    {
        $this->recortes[] = ['tipo' => 'retangulo_arredondado', 'args' => [$x1, $y1, $w, $h, $rTL, $rTR, $rBR, $rBL]];
        parent::clipping_roundrectangle($x1, $y1, $w, $h, $rTL, $rTR, $rBR, $rBL);
    }

    public function clipping_polygon(array $points): void
    {
        $this->recortes[] = ['tipo' => 'poligono', 'args' => [$points]];
        parent::clipping_polygon($points);
    }

    public function clipping_end()
    {
        array_pop($this->recortes);
        parent::clipping_end();
    }

    /**
     * Desenha, por cima de tudo, a grade guardada para a pagina atual.
     * Chamado ao fim da renderizacao de cada pagina.
     */
    public function desenharGrade(): void
    {
        $pagina = $this->get_page_number();
        $tracos = $this->mesclar($this->grade[$pagina] ?? []);
        unset($this->grade[$pagina]);
        if ($tracos === []) {
            return;
        }

        $opacidadeAnterior = $this->_current_opacity;
        $this->set_opacity(1.0);
        foreach ($tracos as $traco) {
            foreach ($traco['recortes'] as $recorte) {
                $this->abrirRecorte($recorte);
            }
            $this->desenhar($traco);
            foreach ($traco['recortes'] as $_) {
                parent::clipping_end();
            }
        }
        $this->set_opacity($opacidadeAnterior);
    }

    /** @return array<int, list<array<string, mixed>>> */
    public function gradePendente(): array
    {
        return $this->grade;
    }

    private function ehGrade(mixed $color): bool
    {
        // O Dompdf 3 monta "hex" com o canal alfa no fim ("#010203FF").
        return is_array($color) && strtolower(substr((string) ($color['hex'] ?? ''), 0, 7)) === self::COR_GRADE;
    }

    /** @param array<string, mixed> $traco */
    private function guardar(array $traco): void
    {
        $traco['recortes'] = $this->recortes;
        $this->grade[$this->get_page_number()][] = $traco;
    }

    /** @param array<string, mixed> $recorte */
    private function abrirRecorte(array $recorte): void
    {
        match ($recorte['tipo']) {
            'retangulo' => parent::clipping_rectangle(...$recorte['args']),
            'retangulo_arredondado' => parent::clipping_roundrectangle(...$recorte['args']),
            'poligono' => parent::clipping_polygon(...$recorte['args']),
        };
    }

    /** @param array<string, mixed> $traco */
    private function desenhar(array $traco): void
    {
        $p = $traco['pontos'];
        match ($traco['tipo']) {
            'linha' => parent::line($p[0], $p[1], $p[2], $p[3], self::COR_TRACO, $traco['largura'], $traco['estilo'], $traco['ponta']),
            'retangulo' => parent::rectangle($p[0], $p[1], $p[2], $p[3], self::COR_TRACO, $traco['largura'], $traco['estilo'], $traco['ponta']),
            'arco' => parent::arc($p[0], $p[1], $p[2], $p[3], $p[4], $p[5], self::COR_TRACO, $traco['largura'], $traco['estilo'], $traco['ponta']),
            'poligono' => parent::polygon($p, self::COR_TRACO, $traco['largura'], $traco['estilo'], $traco['preenchido']),
            'retangulo_cheio' => parent::filled_rectangle($p[0], $p[1], $p[2], $p[3], self::COR_TRACO),
        };
    }

    /**
     * Remove repeticoes e une segmentos retos colineares que se tocam ou se
     * sobrepoem (mesma espessura, ponta e sem recorte). A extensao total e a
     * espessura ficam identicas as do Dompdf; so deixa de haver traco duplo.
     *
     * @param list<array<string, mixed>> $tracos
     * @return list<array<string, mixed>>
     */
    private function mesclar(array $tracos): array
    {
        $grupos = [];
        $resto = [];
        $vistos = [];
        foreach ($tracos as $traco) {
            $chave = serialize($traco);
            if (isset($vistos[$chave])) {
                continue;
            }
            $vistos[$chave] = true;

            [$x1, $y1, $x2, $y2] = $traco['tipo'] === 'linha' ? $traco['pontos'] : [0, 0, 0, 0];
            $retaSimples = $traco['tipo'] === 'linha' && $traco['recortes'] === [] && $traco['estilo'] === [];
            if ($retaSimples && abs($y1 - $y2) < self::TOLERANCIA) {
                $grupos['h|' . round($y1, 2) . '|' . $traco['largura'] . '|' . $traco['ponta']][] = [min($x1, $x2), max($x1, $x2), $traco];
            } elseif ($retaSimples && abs($x1 - $x2) < self::TOLERANCIA) {
                $grupos['v|' . round($x1, 2) . '|' . $traco['largura'] . '|' . $traco['ponta']][] = [min($y1, $y2), max($y1, $y2), $traco];
            } else {
                $resto[] = $traco;
            }
        }

        $mesclados = [];
        foreach ($grupos as $chave => $intervalos) {
            $horizontal = $chave[0] === 'h';
            usort($intervalos, static fn (array $a, array $b): int => $a[0] <=> $b[0]);
            $atual = null;
            foreach ($intervalos as [$inicio, $fim, $traco]) {
                if ($atual !== null && $inicio <= $atual[1] + self::TOLERANCIA) {
                    $atual[1] = max($atual[1], $fim);
                    continue;
                }
                if ($atual !== null) {
                    $mesclados[] = $this->retaUnida($atual, $horizontal);
                }
                $atual = [$inicio, $fim, $traco];
            }
            if ($atual !== null) {
                $mesclados[] = $this->retaUnida($atual, $horizontal);
            }
        }

        // Ordem estavel: primeiro os tracos sem fusao (moldura, divisorias),
        // depois as retas unidas; todos ficam acima do conteudo da pagina.
        return array_merge($resto, $mesclados);
    }

    /**
     * @param array{0: float, 1: float, 2: array<string, mixed>} $intervalo
     * @return array<string, mixed>
     */
    private function retaUnida(array $intervalo, bool $horizontal): array
    {
        [$inicio, $fim, $traco] = $intervalo;
        [$x1, $y1] = $traco['pontos'];
        $traco['pontos'] = $horizontal ? [$inicio, $y1, $fim, $y1] : [$x1, $inicio, $x1, $fim];
        return $traco;
    }
}
