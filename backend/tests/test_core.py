import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import author_matches, h_index, i10_index, venue_core
from validate import paper_status

P = {"names": ["Michiharu Nakamura"], "openalex_ids": ["A1"], "slug": "m"}


def test_names():
    assert author_matches("M Nakamura", P["names"])
    assert author_matches("Nakamura Michiharu", P["names"])
    assert not author_matches("K Nakamura", P["names"])
    assert not author_matches("Nakamura", P["names"])


def test_names_more():
    n = ["Huan-Bang Li", "Huanbang Li"]
    assert author_matches("LI Huan-Bang", n) and author_matches("LI Huanbang", n) and author_matches("Huan-Bang Li", n)
    assert author_matches("Duc-Phuc Nguyen", ["Nguyen Duc Phuc"]) and author_matches("Phuc Duc Nguyen", ["Nguyen Duc Phuc"])
    assert not author_matches("Lin Shan", n)


def test_names_ja():
    assert author_matches("李還幇", ["Huan-Bang Li", "李 還幇"]) and author_matches("単麟, 李 還幇", ["李 還幇"])
    assert not author_matches("三浦龍", ["李 還幇"])


def test_venue_core():
    assert venue_core("IEEE Access 9, 123-456") == "IEEE Access"
    assert venue_core("GLOBECOM 2020 - 2020 IEEE Global Communications Conference") == "GLOBECOM 2020 - 2020 IEEE Global Communications Conference"


def test_venue_core_more():
    for raw, want in [("MOLECULAR BIOLOGY OF THE CELL 24, 2013", "MOLECULAR BIOLOGY OF THE CELL"),
                      ("Advanced Biosystems 3 (9), 1970091, 2019", "Advanced Biosystems"),
                      ("Biophys. J. 70, A159, 1996", "Biophys. J."),
                      ("Seibutsu Butsuri 51 (supplement), S98, 2011", "Seibutsu Butsuri"),
                      ("IEEE Transactions on Wireless Communications 22 (3), 1-15, 2023", "IEEE Transactions on Wireless Communications"),
                      ("Dyneins: Structure, Biology and Disease, 2-35, 2018", "Dyneins: Structure, Biology and Disease"),
                      ("ICC 2021-IEEE International Conference on Communications, 1-6, 2021", "ICC 2021-IEEE International Conference on Communications")]:
        assert venue_core(raw) == want, (raw, venue_core(raw))


def test_h():
    assert h_index([10, 8, 5, 4, 3]) == 4
    assert i10_index([10, 9, 11]) == 2


def paper(authors, cut=False):
    return {"title": "x", "authors": authors, "authors_cut": cut, "year": 2020}


def test_status():
    assert paper_status(paper("M Nakamura, K Sato"), P, [])[0] == "listed"
    assert paper_status(paper("K Sato, J Doe"), P, [])[0] == "not_listed"
    assert paper_status(paper("K Sato, J Doe, ...", True), P, [])[0] == "unconfirmed"
    rec = {"id": "W1", "year": 2020, "authors": [{"id": "A1", "name": "M. Nakamura", "raw": ""}]}
    assert paper_status(paper("K Sato, ...", True), P, [rec])[0] == "verified"
    other = {"id": "W2", "year": 2020, "authors": [{"id": "A9", "name": "K Sato", "raw": ""}]}
    assert paper_status(paper("K Sato"), P, [other])[0] == "not_listed"
    assert paper_status(paper("K Sato"), P, [other], {"decision": "yes", "note": "mine"})[0] == "maintainer"


def test_period():
    q = dict(P, period_from="2015", period_to="2019")
    inside = dict(paper("M Nakamura, K Sato"), year=2017)
    assert paper_status(inside, q, [])[0] == "listed"
    assert paper_status(dict(inside, year=2021), q, [])[0] == "outside"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

