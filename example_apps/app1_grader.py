# sort_grader.py - Intro Level: Sorting and Searching
import time
import random
import submission

def test_sorting():
    print("[*] Testing Sorting Algorithm...")
    test_cases = [
        [random.randint(0, 1000) for _ in range(5000)],
        list(range(5000, 0, -1)),
        [1] * 5000
    ]
    
    start = time.time()
    for case in test_cases:
        expected = sorted(case)
        result = submission.student_sort(case)
        if result != expected:
            print(f"  [FAIL] Sorting failed for case.")
            return False
    
    duration = time.time() - start
    print(f"  [PASS] Sorting tests completed in {duration:.4f}s")
    return True

if __name__ == "__main__":
    print("=== ASSIGNMENT 1: DATA STRUCTURES BASELINE ===")
    if test_sorting():
        print("Final Grade: 100/100")
    else:
        print("Final Grade: 0/100")
