class Counter:
    def __init__(self):
        self.count = 0
        self.history = []

    def increment(self):
        self.count += 1
        self.history.append("inc")

    def decrement(self):
        self.count -= 1
        self.history.append("dec")

    def reset(self):
        self.count = 0
        self.history.append("reset")

    def value(self):
        return self.count
