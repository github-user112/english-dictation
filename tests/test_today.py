"""今日动线聚合接口：任务卡从现有学习表实时推导。"""
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.db import db
from backend.today import build_today

USER = "c" * 32
TODAY = date.today().isoformat()
STAMP = datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(client):
    return client.get(f"/api/today?u={USER}")


@pytest.fixture
def conn():
    with db() as c:
        yield c


def add_goal(list_key="test_words", days=30):
    with db() as c:
        c.execute(
            "INSERT INTO study_goal(user,list,target_days,start_day,updated_at) VALUES(?,?,?,?,?)",
            (USER, list_key, days, TODAY, STAMP))


def test_today_fresh_user(client):
    d = get(client).get_json()
    assert d["has_wordtest"] is False
    assert d["all_done"] is False
    assert d["streak"] == 0
    keys = [s["key"] for s in d["steps"]]
    assert keys == ["memorize", "dictation", "sentence", "arrange", "wrong"]
    # 无计划时背词配额走默认 10；错词步无到期即视为完成
    assert d["steps"][0]["target"] == 10
    assert d["steps"][4]["done"] is True
    assert "list=test_words" in d["steps"][0]["link"]
    assert d["steps"][2]["link"].endswith("lesson=1")


def test_today_uses_goal_quota(client):
    add_goal(days=1)   # 5 个词 1 天背完 → 配额 5
    d = get(client).get_json()
    assert d["goal"]["daily_new"] == 5
    assert d["steps"][0]["target"] == 5
    assert d["steps"][1]["target"] == 5   # min(15, 配额)


def test_today_memorize_progress(client):
    with db() as c:
        for i in (1, 2, 3):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,memorized,memorize_count,last_memorize)"
                " VALUES(?,?,?,'word',1,2,?)", (USER, "test_words", f"w{i}", TODAY))
    d = get(client).get_json()
    step = d["steps"][0]
    assert (step["progress"], step["done"]) == (3, False)


def test_today_dictation_counts_only_target_list(client):
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','memorized','daily',NULL,?,0,'active',?,?,NULL)",
                  (USER, "test_words", TODAY, STAMP, STAMP))
        for i in range(10):
            c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                      " VALUES('s1',?,?,'word','new','completed',1)", (i + 1, f"w{i}"))
        # 别的词库的练习不计入目标词库
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','daily',NULL,?,0,'active',?,?,NULL)",
                  (USER, "test_sents", TODAY, STAMP, STAMP))
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                  " VALUES('s2',1,'1','sentence','new','completed',1)")
    d = get(client).get_json()
    assert d["steps"][1]["progress"] == 10
    assert d["steps"][1]["done"] is True


def test_today_lesson_stays_on_same_day_completion(client):
    """今天完成的课当天不跳：今天打卡的还是这一课；明天才推进。"""
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s9',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", TODAY, STAMP, STAMP, STAMP))
    d = get(client).get_json()
    assert d["lesson"] == 1
    assert "lesson=1" in d["steps"][2]["link"]
    # 第 1 课会话是今天完成的 → 句子步直接算完成（不强迫立刻再学第 2 课）
    assert d["steps"][2]["done"] is True


def test_today_lesson_advances_next_day(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s9',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
    d = get(client).get_json()
    assert d["lesson"] == 2
    assert "lesson=2" in d["steps"][2]["link"]
    assert d["steps"][2]["done"] is False


def test_today_wrong_step(client):
    with db() as c:
        c.execute(
            "INSERT INTO word_state(user,list,item_id,kind,status,wrong_count,next_review)"
            " VALUES(?,?,?, 'word','learning',2,?)", (USER, "test_words", "w1", TODAY))
    d = get(client).get_json()
    step = d["steps"][4]
    assert step["done"] is False and step["target"] == 1


def test_today_nce_words_pair_same_book_sentences(client):
    """nceN 词汇必须配 ncN 课文（防切片回归：nce2[2:]=='e2' 曾拼出 ne2）。"""
    from backend.today import _pick_lists
    fake = {"nce2": {"type": "words", "title": "w"}, "nc2": {"type": "sentences", "title": "s"}}
    from unittest.mock import patch
    with patch("backend.today.MATERIALS", fake), db() as c:
        assert _pick_lists(c, USER, None) == ("nce2", "nc2")


def test_today_wordtest_recommendation(client):
    with db() as c:
        c.execute(
            "INSERT INTO wordtest_result(user,level,questions_answered,correct_count,cefr,word_count,detail,created_at)"
            " VALUES(?,7,25,18,'B1',3500,'[]',?)", (USER, STAMP))
    d = get(client).get_json()
    assert d["has_wordtest"] is True and d["wordtest"]["cefr"] == "B1"
    # B1 → nce2/nc2，但测试环境没有这两个素材 → 退到同类第一个
    assert d["word_list"]["key"] == "test_words"
    assert d["sent_list"]["key"] == "test_sents"


def get_nce(client):
    """课程模式：test_nce 词库（课号 1,3）+ test_sents 句库（课号 1,2）。"""
    return client.get(f"/api/today?u={USER}&list=test_nce")


def test_lesson_mode_layout(client):
    d = get_nce(client).get_json()
    assert d["lesson_mode"] is True
    assert d["goal"] is None                      # 按课不按量，学习计划不参与
    assert d["lesson"] == 1 and d["lesson_total"] == 2
    keys = [s["key"] for s in d["steps"]]
    assert keys == ["memorize", "dictation", "sentence", "arrange", "wrong"]
    mem, dic, sent = d["steps"][:3]
    assert mem["target"] == 2 and mem["desc"] == "第 1 课 · 2 个单词"
    assert "list=test_nce&lesson=1" in mem["link"]
    assert dic["link"].endswith("list=test_nce&lesson=1")
    assert "list=test_sents&lesson=1" in sent["link"]
    assert sent["target"] == 2                    # test_sents 第 1 课 2 句


def test_lesson_mode_word_lesson_mapping(client):
    """句库第 2 课 ↔ 词库第 3 课（nce1 双课合并：词课号 = 2L-1）。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s9',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
    d = get_nce(client).get_json()
    assert d["lesson"] == 2
    mem = d["steps"][0]
    assert mem["desc"] == "第 2 课 · 2 个单词"
    assert "lesson=3" in mem["link"]                  # 词库课号 2L-1
    assert "lesson=3" in d["steps"][1]["link"]
    assert "list=test_sents&lesson=2" in d["steps"][2]["link"]   # 句库课号不变


def test_lesson_mode_word_steps_completion(client):
    with db() as c:
        for w in ("excuse", "pardon"):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,memorized,memorize_count,last_memorize)"
                " VALUES(?,?,?,'word',1,2,?)", (USER, "test_nce", w, TODAY))
        # 整课听打会话打完即算完成，哪怕有词最终没拼对（错词本兜底回收）
        c.execute("INSERT INTO study_session VALUES('w1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_nce", TODAY, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                  " VALUES('w1',1,'excuse','word','new','completed',1)")
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                  " VALUES('w1',2,'pardon','word','new','completed',0)")
    d = get_nce(client).get_json()
    mem, dic = d["steps"][:2]
    assert mem["done"] is True and mem["progress"] == 2
    assert dic["done"] is True and dic["progress"] == 1


def test_word_lesson_mapping():
    from backend.today import _word_lesson
    assert _word_lesson([1, 3, 5], [1, 2, 3], 2) == 3       # nce1 双课合并
    assert _word_lesson([1, 2, 3], [1, 2, 3], 2) == 2       # 课号一致的册
    assert _word_lesson([1, 2, 4], [1, 2, 3, 4], 3) is None  # 词库缺课（如 nce4 第 21 课）
    assert _word_lesson([1, 2], [1, 2, 3], 3) is None        # 课号超出词库范围
    assert _word_lesson([], [1], 1) is None


def test_lesson_mode_same_lesson_two_sessions(client):
    """同课两个会话：昨天完成的 + 今天重练中的 → 留在本课，且句子步不算完成（完成只看今天）。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','lesson',1,?,0,'active',?,?,NULL)",
                  (USER, "test_sents", TODAY, STAMP, STAMP))
    d = get_nce(client).get_json()
    assert d["lesson"] == 1
    assert d["steps"][2]["done"] is False


def test_today_all_done(client):
    with db() as c:
        for i in range(10):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,memorized,memorize_count,last_memorize)"
                " VALUES(?,?,?,'word',1,2,?)", (USER, "test_words", f"w{i}", TODAY))
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','memorized','daily',NULL,?,0,'completed',?,?,?)",
                  (USER, "test_words", TODAY, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", TODAY, STAMP, STAMP, STAMP))
        for i in range(15):
            c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                      " VALUES('s1',?,?,'word','new','completed',1)", (i + 1, f"w{i}"))
        c.execute("INSERT INTO daily_practice_log(day,user,practice_mode,final_right_count)"
                  " VALUES(?,?,'arrange',5)", (TODAY, USER))
        c.execute("INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at)"
                  " VALUES(?,?,'test_words',8,10,'[]',?)", (TODAY, USER, STAMP))
    d = get(client).get_json()
    assert d["all_done"] is True
    assert d["done_count"] == len(d["steps"])
    assert d["daily_done"] is True
    assert d["streak"] == 1
