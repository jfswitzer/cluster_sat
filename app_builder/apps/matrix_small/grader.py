#!/usr/bin/env python3
import time
import random
import submission

def test_matrix_mult():
    print("[*] Testing 70x70 Matrix Multiplication...")
    size = 70
    m1 = [[random.random() for _ in range(size)] for _ in range(size)]
    m2 = [[random.random() for _ in range(size)] for _ in range(size)]

    start = time.time()
    result = submission.multiply(m1, m2)
    duration = time.time() - start

    if len(result) == size and len(result[0]) == size:
        print(f"  [PASS] Matrix multiplication completed in {duration:.4f}s")
        print("Final Grade: 100/100")
        return True
    print("Final Grade: 0/100")
    return False

if __name__ == "__main__":
    print("=== ASSIGNMENT: SMALL COMPUTE TEST ===")
    try:
        test_matrix_mult()
    except Exception as e:
        print(f"Grader error: {e}")
        raise
