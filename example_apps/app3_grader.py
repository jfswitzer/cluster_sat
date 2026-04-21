# matrix_grader.py - Advanced Level: Linear Algebra (CPU INTENSIVE)
import time
import random
import submission

def test_matrix_mult():
    print("[*] Testing 400x400 Matrix Multiplication...")
    size = 400
    m1 = [[random.random() for _ in range(size)] for _ in range(size)]
    m2 = [[random.random() for _ in range(size)] for _ in range(size)]
    
    start = time.time()
    result = submission.multiply(m1, m2)
    duration = time.time() - start
    
    if len(result) == size and len(result[0]) == size:
        print(f"  [PASS] Matrix multiplication completed in {duration:.4f}s")
        return True
    return False

if __name__ == "__main__":
    print("=== ASSIGNMENT 3: HEAVY COMPUTE BOUND ===")
    if test_matrix_mult():
        print("Final Grade: 100/100")
    else:
        print("Final Grade: 0/100")
