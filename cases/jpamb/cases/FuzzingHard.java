package jpamb.cases;

import static jpamb.utils.Tag.TagType.*;

import jpamb.utils.Case;
import jpamb.utils.Tag;

// Benchmark methods written by Christian to test the fuzzer's features.
public class FuzzingHard {

    // Only the exact index 4242 is out of bounds: needs a constant from the
    // program.
    @Case("(0) -> ok")
    @Case("(4242) -> out of bounds")
    @Tag({ ARRAY })
    public static int magicIndex(int i) {
        int[] a = new int[8];
        if (i == 4242) {
            return a[i];
        }
        return 0;
    }

    // 3x + 5y == 1000003 has solutions, but neither x nor y can be a program
    // constant.
    // Reaching the branch gives coverage no hint of how close an input was.
    @Case("(0, 0) -> ok")
    @Case("(333321, 8) -> out of bounds")
    @Case("(333321, 7) -> ok")
    @Tag({ ARRAY })
    public static int linearRelation(int x, int y) {
        int[] a = new int[4];
        if (3 * x + 5 * y == 1000003 && y > 7) {
            return a[4];
        }
        return 0;
    }

    // Two stages: a must match first, then b. Each stage reaches new code, so
    // coverage feedback can build on partial progress; guessing both at once is
    // hopeless.
    @Case("(0, 0) -> ok")
    @Case("(1111, 0) -> ok")
    @Case("(1111, 2222) -> divide by zero")
    @Case("(0, 2222) -> ok")
    public static int stagedInts(int a, int b) {
        if (a == 1111) {
            if (b == 2222) {
                return 1 / (a - 1111);
            }
        }
        return 0;
    }

    // Needs exactly length 8 and a[3] == 2 * a[5].
    @Case("([I:]) -> ok")
    @Case("([I: 0, 0, 0, 0, 0, 0, 0, 0]) -> out of bounds")
    @Case("([I: 0, 0, 0, 1, 0, 0, 0, 0]) -> ok")
    @Tag({ ARRAY })
    public static int arrayShape(int[] a) {
        if (a.length == 8 && a[3] == 2 * a[5]) {
            return a[a.length];
        }
        return 0;
    }

    // Fails only for the exact string "open sesame": needs a string constant from
    // the program.
    @Case("(s'') -> ok")
    @Case("(s'open sesame') -> assertion error")
    public static void secretPhrase(String s) {
        assert !s.equals("open sesame");
    }
}