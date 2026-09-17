<?php

namespace GuilhermeViana\Nfsenacional\Danfse\Dto;

/**
 * Imóvel da operação (bloco IBSCBS da DPS, reforma tributária).
 *
 * Precisa de mais de um parâmetro: com um único argumento o valinor usa o
 * atalho de "objeto de argumento único" e tenta converter o array inteiro
 * (`{end: {...}}`) em string, rejeitando o XML com "Invalid value" em
 * infNFSe. Era o caso das NFS-e de São Luís que traziam `imovel/end`.
 */
readonly class Imovel
{
    public function __construct(
        public string $inscImobFisc = '',
        public ?Endereco $end = null,
    ) {}
}
