<?php

namespace GuilhermeViana\Nfsenacional\Danfse\Dto;

readonly class Valores
{
    public function __construct(
        public ?VServPrest $vServPrest = null,
        public ?Tributacao $trib = null,
        // Grupo no leiaute nacional (vDescIncond/vDescCond); como string o mapeador
        // rejeitava o XML inteiro ("Invalid value" em infDPS.valores).
        public ?VDescCondIncond $vDescCondIncond = null,
    ) {}
}
