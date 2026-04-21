# prime_grader.py - Intermediate Level: Number Theory
import time
import submission

def test_primes():
    print("[*] Testing Prime Generation up to 1,000,000...")
    limit = 1000000
    
    start = time.time()
    student_primes = submission.find_primes(limit)
    duration = time.time() - start
    
    # Quick sanity check on count
    # There are 78,498 primes under 1,000,000
    if len(student_primes) == 78498:
        print(f"  [PASS] Found correct number of primes in {duration:.4f}s")
        return True
    else:
        print(f"  [FAIL] Incorrect prime count: {len(student_primes)}")
        return False

if __name__ == "__main__":
    print("=== ASSIGNMENT 2: COMPUTATIONAL LOOPS ===")
    if test_primes():
        print("Final Grade: 100/100")
    else:
        print("Final Grade: 0/100")
