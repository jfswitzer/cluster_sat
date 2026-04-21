import re
import csv
import os

def parse_benchmark_file(input_filename, output_filename):
    # Regex patterns to find specific data points
    concurrency_pattern = re.compile(r"Concurrency=(\d+)")
    throughput_pattern = re.compile(r"Overall Throughput:\s+([\d.]+)")
    # Pattern for the table rows: app_type | avg_latency | p95
    table_row_pattern = re.compile(r"(sort|primes|matrix)\s+\|\s+([\d.]+)\s+\|\s+([\d.]+)")

    data_rows = []
    
    # Check if file exists
    if not os.path.exists(input_filename):
        print(f"Error: {input_filename} not found.")
        return

    current_concurrency = None
    current_throughput = None

    with open(input_filename, 'r') as f:
        for line in f:
            # 1. Look for the start of a new benchmark block
            concurrency_match = concurrency_pattern.search(line)
            if concurrency_match:
                current_concurrency = concurrency_match.group(1)
                continue

            # 2. Look for the overall throughput of this run
            throughput_match = throughput_pattern.search(line)
            if throughput_match:
                current_throughput = throughput_match.group(1)
                continue

            # 3. Look for application specific rows
            table_match = table_row_pattern.search(line)
            if table_match and current_concurrency:
                app_type = table_match.group(1)
                avg_latency = table_match.group(2)
                p95_latency = table_match.group(3)
                
                # Create a row for the CSV
                data_rows.append({
                    'concurrency': current_concurrency,
                    'app_type': app_type,
                    'avg_latency_s': avg_latency,
                    'p95_latency_s': p95_latency,
                    'overall_throughput_jps': current_throughput
                })

    # Write to CSV
    headers = ['concurrency', 'app_type', 'avg_latency_s', 'p95_latency_s', 'overall_throughput_jps']
    
    with open(output_filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data_rows)

    print(f"Successfully parsed {len(data_rows)} data points into {output_filename}")

if __name__ == "__main__":
    # Change 'benchmark_logs.txt' to whatever your input file is named
    input_file = 'results.txt'
    output_file = 'benchmark_results.csv'

    parse_benchmark_file(input_file, output_file)
