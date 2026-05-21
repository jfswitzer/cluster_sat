# matrix_submission.py
def multiply(A, B):
    """Simple O(N^3) matrix multiplication."""
    size = len(A)
    result = [[0 for _ in range(size)] for _ in range(size)]
    for i in range(size):
        for j in range(size):
            for k in range(size):
                result[i][j] += A[i][k] * B[k][j]
    return result
