#include <iostream>
#include <string>

extern "C" int add_score(int current, int points);
extern "C" int subtract_score(int current, int points);
extern "C" int reset_score(int current);

int main() {
    std::string nonce;
    std::string operation;
    int current = 0;
    int points = 0;
    while (std::cin >> nonce >> operation >> current >> points) {
        int answer;
        if (operation == "add") answer = add_score(current, points);
        else if (operation == "subtract") answer = subtract_score(current, points);
        else if (operation == "reset") answer = reset_score(current);
        else return 2;
        std::cout << nonce << ' ' << answer << std::endl;
    }
    return 0;
}
