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


def test_vtc():
    from venues import classify
    for v in ["arXiv preprint arXiv:2607.14500, VTC Fall'26, 2026", "2022 IEEE 96 th Vehicular Technology Conference, 2022"]:
        c = classify(v)
        assert (c["kind"], c["core_rank"]) == ("conference", "B"), (v, c)
    assert classify("arXiv preprint arXiv:2101.00001")["kind"] == "preprint"


def test_icc_older_edition():
    from venues import classify
    c = classify("ICC 2021-IEEE International Conference on Communications, 1-6, 2021")
    assert (c["kind"], c["core_rank"]) == ("conference", "B"), c


def test_rank_at_the_time():
    from venues import classify
    im = "2021 IFIP/IEEE International Symposium on Integrated Network Management (IM, 2021"
    assert classify(im, year=2021)["core_rank"] == "A"      # CORE2020 lacks IM; CORE2018 has A
    assert classify(im, year=2023)["core_rank"] == "B"      # CORE2021 lists IM as B


def test_ccnc_is_b_not_a_common_word():
    from venues import classify
    for y in (2010, 2021, 2026):
        c = classify("IEEE Consumer Communications & Networking Conference (CCNC)", year=y)
        assert (c["kind"], c["core_rank"]) == ("conference", "B"), (y, c)
    c = classify("2026 IEEE 23rd Consumer Communications &amp; Networking Conference (CCNC)", year=2026)
    assert c["core_rank"] == "B", c


def test_workshop_takes_no_rank():
    from venues import classify
    for v in ["IEEE INFOCOM 2021 - IEEE Conference on Computer Communications Workshops (INFOCOM WKSHPS)",
              "2020 IEEE International Conference on Communications Workshops (ICC Workshops)",
              "Companion Proceedings of the Web Conference 2021"]:
        c = classify(v, year=2021)
        assert c["core_rank"] != "A*" and c["core_rank"] in ("", "Unranked", "B", "C", "A") and "side event" in c["how"] or c["core_rank"] == "Unranked", (v, c)
    assert classify("IEEE INFOCOM 2022 - IEEE Conference on Computer Communications", year=2022)["core_rank"] == "A*"


def test_middle_names():
    n = ["Gabriel Villardi"]
    assert author_matches("Gabriel Porto Villardi", n) and author_matches("GP Villardi", n) and author_matches("G Villardi", n)
    assert not author_matches("Gabriel Santos Silva", n) and not author_matches("Villardi", n)
    assert author_matches("M Nakamura", ["Michiharu Nakamura"]) and not author_matches("Masaki Nakamura", ["Michiharu Nakamura"])
    assert not author_matches("K Nakamura", ["Michiharu Nakamura"])


def test_openalex_source_names():
    from venues import classify
    # OpenAlex prints the source without the society prefix, or under another name than CORE
    assert classify("International Conference on Communications", year=2021)["core_rank"] == "B"          # ICC
    assert classify("Integrated Network Management", year=2021)["core_rank"] == "A"                       # IM, CORE2018
    assert classify("Malaysia International Conference on Communications", year=2019)["core_rank"] != "B"  # a different conference


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

