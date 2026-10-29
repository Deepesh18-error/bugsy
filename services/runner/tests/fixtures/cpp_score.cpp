extern "C" int add_score(int current, int points) { return current + points; }
extern "C" int subtract_score(int current, int points) { return current - points; }
extern "C" int reset_score(int current) { (void)current; return 0; }
