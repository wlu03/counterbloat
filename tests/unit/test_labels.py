from backend.ingestion import labels

RECENT = {"form": ["8-K", "8-K", "10-K", "8-K/A"],
          "items": ["2.02,9.01", "4.02,8.01", "", "4.02"],
          "filingDate": ["2017-02-01", "2017-06-15", "2017-03-01", "2019-01-10"],
          "accessionNumber": ["a-1", "a-2", "a-3", "a-4"]}


def test_only_non_reliance_items_are_collected(monkeypatch):
    monkeypatch.setattr(labels, "read_json", lambda url: {"filings": {"recent": RECENT}})
    found = labels.events("320193")
    assert [e.accession for e in found] == ["a-4", "a-2"]
    # 4.02 must not be matched inside another item number such as 14.02.
    block = dict(RECENT, items=["14.02", "", "", ""], form=["8-K", "8-K", "8-K", "8-K"])
    monkeypatch.setattr(labels, "read_json", lambda url: {"filings": {"recent": block}})
    assert labels.events("320193") == []


def test_a_window_after_the_call_is_what_counts(monkeypatch):
    monkeypatch.setattr(labels, "read_json", lambda url: {"filings": {"recent": RECENT}})
    found = labels.events("320193")
    assert [e.accession for e in labels.within(found, "2017-01-15", 12)] == ["a-2"]
    # Two years reaches the 2019 filing as well.
    assert [e.accession for e in labels.within(found, "2017-01-15", 24)] == ["a-4", "a-2"]
    assert labels.within(found, "2017-01-15", 3) == []
    # The window end rolls into the next year from the month count.
    assert labels.within(found, "2018-12-01", 2)[0].accession == "a-4"
