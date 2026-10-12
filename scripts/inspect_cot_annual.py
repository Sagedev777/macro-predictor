import os

if os.path.exists('annual.txt'):
    with open('annual.txt', 'r', encoding='latin-1') as f:
        matches = 0
        for i, line in enumerate(f):
            if 'GOLD' in line and 'COMMODITY EXCHANGE' in line:
                parts = [p.strip(' "\n') for p in line.split(',')]
                print(f"Date: {parts[2]} | {parts[0]} | OI: {parts[7]} | Long: {parts[8]} | Short: {parts[9]}")
                matches += 1
                if matches >= 5:
                    break
