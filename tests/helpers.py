class Clerk:
    """เลียนแบบคนพิมพ์ที่ตอบคำถามของโปรแกรม: ค่าเริ่มต้นตอบ 'ใช่' ทุกข้อ"""

    def __init__(self, answers=None, actions=None):
        self.answers = answers or {}
        self.actions = actions or {}
        self.asked = []

    def __call__(self, kind, message, screen):
        self.asked.append(kind)
        if kind in self.actions:
            self.actions[kind]()
        return self.answers.get(kind, True)
