from firebreak.brain import to_query


def test_query_drops_stopwords_and_ors_terms():
    q = to_query("Why does checkout call auth synchronously?")
    assert q.split("|") == ["checko*", "call", "auth", "synchronous*"]


def test_query_falls_back_to_raw_question():
    assert to_query("why is it") == "why is it"
