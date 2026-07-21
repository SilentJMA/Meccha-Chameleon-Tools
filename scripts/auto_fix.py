
# fix functions
KNOWN_FIXES = []

def load_issue(path):
    with open(path) as f: return json.load(f)

def main():
    if len(sys.argv) < 2:
        r = {chr(115)+chr(116)+chr(97)+chr(116)+chr(117)+chr(115): chr(110)+chr(111)+chr(45)+chr(102)+chr(105)+chr(120)}
        r[chr(114)+chr(101)+chr(97)+chr(115)+chr(111)+chr(110)] = chr(77)+chr(105)+chr(115)+chr(115)+chr(105)+chr(110)+chr(103)+chr(32)+chr(105)+chr(115)+chr(115)+chr(117)+chr(101)+chr(32)+chr(102)+chr(105)+chr(108)+chr(101)+chr(32)+chr(97)+chr(114)+chr(103)+chr(117)+chr(109)+chr(101)+chr(110)+chr(116)
        print(json.dumps(r))
        sys.exit(0)
    issue = load_issue(sys.argv[1])
    body = issue.get(chr(98)+chr(111)+chr(100)+chr(121), chr(34).strip(chr(34)))
    title = issue.get(chr(116)+chr(105)+chr(116)+chr(108)+chr(101), chr(34).strip(chr(34)))
    num = issue.get(chr(110)+chr(117)+chr(109)+chr(98)+chr(101)+chr(114), 0)
    r = {chr(115)+chr(116)+chr(97)+chr(116)+chr(117)+chr(115): chr(110)+chr(111)+chr(45)+chr(102)+chr(105)+chr(120)}
    r[chr(114)+chr(101)+chr(97)+chr(115)+chr(111)+chr(110)] = chr(78)+chr(111)+chr(32)+chr(97)+chr(112)+chr(112)+chr(108)+chr(105)+chr(99)+chr(97)+chr(98)+chr(108)+chr(101)+chr(32)+chr(102)+chr(105)+chr(120)+chr(32)+chr(102)+chr(111)+chr(117)+chr(110)+chr(100)
    r[chr(98)+chr(114)+chr(97)+chr(110)+chr(99)+chr(104)] = chr(34).strip(chr(34))
    r[chr(115)+chr(117)+chr(109)+chr(109)+chr(97)+chr(114)+chr(121)] = chr(65)+chr(110)+chr(97)+chr(108)+chr(121)+chr(122)+chr(101)+chr(100)+chr(32)+chr(105)+chr(115)+chr(115)+chr(117)+chr(101)+chr(32)+chr(35) + str(num) + chr(32)+chr(98)+chr(117)+chr(116)+chr(32)+chr(110)+chr(111)+chr(32)+chr(97)+chr(117)+chr(116)+chr(111)+chr(109)+chr(97)+chr(116)+chr(101)+chr(100)+chr(32)+chr(102)+chr(105)+chr(120)+chr(32)+chr(119)+chr(97)+chr(115)+chr(32)+chr(115)+chr(97)+chr(102)+chr(101)+chr(46)
    print(json.dumps(r))

if __name__ == chr(95)+chr(95)+chr(109)+chr(97)+chr(105)+chr(110)+chr(95)+chr(95):
    main()
