class Wallet:
    def __init__(self):
        self.balance = 0
        self.history = []

    def deposit(self, amount):
        if type(amount) is not int or amount <= 0:
            return False
        self.balance += amount
        self.history.append(amount)
        return True

    def withdraw(self, amount):
        if type(amount) is not int or amount <= 0 or amount > self.balance:
            return False
        self.balance -= amount
        self.history.append(-amount)
        return True

    def statement(self):
        return list(self.history)
