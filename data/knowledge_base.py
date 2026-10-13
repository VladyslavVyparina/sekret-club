"""
Дані бази знань - курси, уроки, ефіри
"""

KNOWLEDGE_BASE = {
    "courses": [
        {
            "id": "vyhid",
            "title": "Курс \"Вихід на новий рівень\"",
            "lessons": [
                {
                    "id": "l1",
                    "title": "🎬Лекція №1: Постановка цілей. Як ставити цілі, щоб досягати їх зі 100% гарантією",
                    "description": "▶️Відео: https://youtu.be/ItK9NEIbCck?si=yPVEh4gn9MmyvBmL",
                    "video_url": "https://youtu.be/ItK9NEIbCck?si=yPVEh4gn9MmyvBmL",
                    "num": 1,
                },
                {
                    "id": "l2",
                    "title": "🎬Лекція №2: Перше «Я» — Душа. Навчитись відчувати душу та виконувати її цілі, плани та задуми",
                    "description": "▶️Запис зустрічі: https://youtu.be/LN-3uFzWT4E",
                    "video_url": "https://youtu.be/LN-3uFzWT4E",
                    "num": 2,
                },
                {
                    "id": "l3",
                    "title": "🎬Лекція №3: Друге \"Я\": УМ. Як приборкати свій ум на шляху до великих досягнень",
                    "description": "▶️Відео: https://youtu.be/swE4qwGXfdY?si=UEllnZRQiza6SUoF",
                    "video_url": "https://youtu.be/swE4qwGXfdY?si=UEllnZRQiza6SUoF",
                    "num": 3,
                },
                {
                    "id": "l4",
                    "title": "🎬Лекція №4: Третє \"Я\": Тіло. Як отримувати тіло у високій енергії та стані мобілізації у досягненні цілей",
                    "description": "▶️Відео: https://youtu.be/rBcgHkN5NrU?si=5-2Pybj_Ernd7B9A",
                    "video_url": "https://youtu.be/rBcgHkN5NrU?si=5-2Pybj_Ernd7B9A",
                    "num": 4,
                },
                {
                    "id": "l5",
                    "title": "🎬Лекція №5: Контекст: Створення середовища та стану, який сприятиме нові моделі поведінки та мислення",
                    "description": "▶️Відео: https://youtu.be/RFfRqdpLoc8?si=xe3qiS-GJhz0VIae",
                    "video_url": "https://youtu.be/RFfRqdpLoc8?si=xe3qiS-GJhz0VIae",
                    "num": 5,
                },
            ],
        },
        {
            "id": "realnist",
            "title": "Курс \"Створення реальності\"",
            "lessons": [],
        },
        {
            "id": "tilo",
            "title": "Курс \"Струнке тіло\"",
            "lessons": [],
        },
        {
            "id": "svidomist",
            "title": "Курс \"Чиста свідомість\"",
            "lessons": [],
        },
        {
            "id": "um",
            "title": "Курс \"Приборкання Ума\"",
            "lessons": [],
        },
    ],
    "streams": [
        {"id": "s1", "title": "Ефір №1"},
        {"id": "s2", "title": "Ефір №2"},
        {"id": "s3", "title": "Ефір №3"},
    ],
    "materials": [
        {"id": "m1", "title": "Корисний матеріал 1"},
        {"id": "m2", "title": "Корисний матеріал 2"},
    ],
    "books": [
        {"id": "b1", "title": "Книга 1"},
        {"id": "b2", "title": "Книга 2"},
    ],
}


def get_course(course_id: str):
    for c in KNOWLEDGE_BASE["courses"]:
        if c["id"] == course_id:
            return c
    return None


def get_lesson(course_id: str, lesson_id: str):
    course = get_course(course_id)
    if not course or not course.get("lessons"):
        return None
    for l in course["lessons"]:
        if l["id"] == lesson_id:
            return l
    return None


def find_lesson_and_course(lesson_id: str):
    """Знайти урок та його курс по lesson_id. Повертає (lesson, course) або (None, None)"""
    for course in KNOWLEDGE_BASE.get("courses", []):
        for lesson in course.get("lessons", []):
            if lesson["id"] == lesson_id:
                return lesson, course
    return None, None
