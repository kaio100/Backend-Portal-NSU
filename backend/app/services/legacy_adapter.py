def legacy_available() -> bool:
    try:
        import adn_nfse_downloader  # noqa: F401
    except Exception:
        return False
    return True
