<?php

namespace GuilhermeViana\Nfsenacional\Danfse\Dto;

/**
 * Atividade de evento (shows, feiras, congressos) da DPS.
 *
 * Com um unico parametro o valinor usava o atalho de "objeto de argumento
 * unico" e tentava converter o array inteiro em string: toda NFS-e de evento
 * artistico era rejeitada ("Invalid value" em infNFSe). Campos conforme o
 * leiaute nacional: xNome, dtIni, dtFim, idAtvEvt e endereco.
 */
readonly class AtvEvento
{
    public function __construct(
        public string $idAtvEvt = '',
        public string $xNome = '',
        public string $dtIni = '',
        public string $dtFim = '',
        public ?Endereco $end = null,
    ) {}
}
