<?php

namespace GuilhermeViana\Nfsenacional\Danfse\Dto;

/** Descontos da DPS (valores/vDescCondIncond) no leiaute nacional. */
readonly class VDescCondIncond
{
    public function __construct(
        public string $vDescIncond = '',
        public string $vDescCond = '',
    ) {}
}
