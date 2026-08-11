from backend.app.repositories.notas_repo import _incidencia_search_term


def test_normaliza_municipio_com_uf_para_filtro_de_incidencia():
    assert _incidencia_search_term("Imperatriz") == "Imperatriz"
    assert _incidencia_search_term("Imperatriz MA") == "Imperatriz"
    assert _incidencia_search_term("Imperatriz/MA") == "Imperatriz"
    assert _incidencia_search_term("Imperatriz - MA") == "Imperatriz"
