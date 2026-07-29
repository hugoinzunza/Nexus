from modules.trading import news


def _event(title, ts):
    return {
        "title": title,
        "country": "USD",
        "impact": "High",
        "ts": ts,
        "forecast": "",
        "previous": "",
    }


def test_fomc_conference_sigue_bloqueando_26_minutos_despues(monkeypatch):
    conference = 1_000_000
    monkeypatch.setattr(
        news, "all_events",
        lambda: [_event("FOMC Press Conference", conference)],
    )

    active = news.danger_window(now=conference + 26 * 60)

    assert active["title"] == "FOMC Press Conference"
    assert active["window_before_min"] == 30
    assert active["window_after_min"] == 90
    assert active["active_until"] == conference + 90 * 60


def test_fomc_agrupa_decision_y_conferencia_en_un_episodio(monkeypatch):
    decision = 1_000_000
    conference = decision + 30 * 60
    monkeypatch.setattr(
        news, "all_events",
        lambda: [
            _event("Federal Funds Rate", decision),
            _event("FOMC Statement", decision),
            _event("FOMC Press Conference", conference),
        ],
    )

    active = news.danger_window(now=conference + 10 * 60)

    assert active["title"] == "FOMC Press Conference"
    assert active["active_until"] == decision + 120 * 60
    assert active["episode_titles"] == [
        "Federal Funds Rate", "FOMC Statement", "FOMC Press Conference",
    ]


def test_evento_generico_no_hereda_ventana_fomc(monkeypatch):
    event_ts = 1_000_000
    monkeypatch.setattr(
        news, "all_events",
        lambda: [_event("ISM Manufacturing PMI", event_ts)],
    )

    assert news.danger_window(now=event_ts + 14 * 60) is not None
    assert news.danger_window(now=event_ts + 16 * 60) is None


def test_status_declara_que_solo_bloquea_entradas(monkeypatch):
    event_ts = 1_000_000
    monkeypatch.setattr(
        news, "all_events",
        lambda: [_event("Federal Funds Rate", event_ts)],
    )

    status = news.fundamental_status(now=event_ts + 30 * 60)

    assert status["blocks_new_entries"] is True
    assert status["active"]["title"] == "Federal Funds Rate"
