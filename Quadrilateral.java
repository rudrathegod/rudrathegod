package music;

import java.util.Random;

public class Quadrilateral {

    /*
* Points are created in clockwise order such that: A is top left B is top right
* C is bottom right D is bottom left
     */
    private Point A = new Point();
    private Point B = new Point();
    private Point C = new Point();
    private Point D = new Point();
    private String type;
// default constructor

    public Quadrilateral() {
        genA();
        genB();
        genC();
        genD();
        type = classify();
    }
// overloaded constructor
/*
* Creates a quadrilateral based upon the String type passed as a parameter.
* type: Parallelogram, Rhombus, Rectangle, Square and Trapezoid EXTRA CREDIT:
* kite Use classify method to initialize type.
     */
    public Quadrilateral(String str) {
// Depending on the type of quadrilateral, adjust
// the coordinates of the points to create the desired shape
        type = str;
        if (type.equalsIgnoreCase("Square")) {
            initSquare();
        } else if (type.equalsIgnoreCase("Rectangle")) {
            initRectangle();
        } else if (type.equalsIgnoreCase("Parallelogram")) {
            initParallelogram();
        } else if (type.equalsIgnoreCase("rhombus")) {
            initRhombus();
        } else if (type.equalsIgnoreCase("trapezoid")) {
            initTrapezoid();
        }
    }
// random PointQuad with x ->[0-100], y->[0,100], x and y are multiples of 10

    private void genA() {
        int x = (int) (Math.random() * 11) * 10;
        int y = (int) (Math.random() * 11) * 10;
        A = new Point(x, y);
    }
// random PointQuad with x ->[100-200], y->[0,100], x and y are multiples of 10

    private void genB() {
        int x = (int) (Math.random() * 10) * 10 + 110;
        int y = (int) (Math.random() * 11) * 10;
        B = new Point(x, y);
    }
// random PointQuad with x ->[100-200], y->[100,200], x and y are multiples of
// 10

    private void genC() {
        int x = (int) (Math.random() * 10) * 10 + 110;
        int y = (int) (Math.random() * 10) * 10 + 110;
        C = new Point(x, y);
    }
// random PointQuad with x ->[0-100], y->[100,200], x and y are multiples of 10

    private void genD() {
        int x = (int) (Math.random() * 11) * 10;
        int y = (int) (Math.random() * 10) * 10 + 110;
        D = new Point(x, y);
    }

    public Point getA() {
        return A;
    }

    public Point getB() {
        return B;
    }

    public Point getC() {
        return C;
    }

    public Point getD() {
        return D;
    }
// Method to calculate the slope of the line formed by two points
/*
* returns true or false based upon if quadrilateral is a parallelogram with all
* equal side and all equal angles.
     */
// Method to determine if a quadrilateral is a square
    public boolean isSquare() {
        if (type.equalsIgnoreCase("Square") && (isRectangle() && isRhombus())) {
            return true;
        }
        return false;
    }

    public boolean isTrapezoid() {
        if (type.equalsIgnoreCase("trapezoid")) {
            return true;
        }
        Rational slopeab = sideSlope(A, B);
        Rational slopebc = sideSlope(B, C);
        Rational slopecd = sideSlope(C, D);
        Rational slopead = sideSlope(A, D);
        if (slopeab == (slopecd) || slopebc.equals(slopead)) {
            return true;
        }
        return false;
    }

    /*
* returns true or false based upon if quadrilateral is a parallelogram. There
* are many sufficient conditions to prove that shape is a parallelogram. You
* can decide to choose any you like.
     */
// Method to determine if a quadrilateral is a parallelogram
    public boolean isParallelogram() {
        if (type.equalsIgnoreCase("Parallelogram")) {
            return true;
        }
        Rational mAB = sideSlope(A, B);
        Rational mBC = sideSlope(B, C);
        Rational mCD = sideSlope(C, D);
        Rational mAD = sideSlope(A, D);
        if (mAB.equals(mCD) && mAD.equals(mBC)) {
            return true;
        }
        return false;
    }

    /*
* returns true or false based upon if quadrilateral is a quadrilateral with all
* 90 degree angles
     */
    public boolean isRectangle() {
        if (type.equalsIgnoreCase("rectangle")) {
            return true;
        }
        Rational side1 = sideSlope(A, B);
        Rational sid2 = sideSlope(B, C);
        Rational checker = new Rational(-side1.getQ(), side1.getP());
        if (isParallelogram() && sid2.equals(checker)) {
            return true;
        }
        return false;
    }

    /*
* returns true or false based upon if quadrilateral is a parallelogram with all
* equal sides
     */
// Method to determine if a quadrilateral is a rhombus
    public boolean isRhombus() {
        double s1 = sideLength(A, B);
        double s2 = sideLength(B, C);
        double s3 = sideLength(C, D);
        double s4 = sideLength(A, D);
        if (type.equalsIgnoreCase("Rhombus")) {
            return true;
        }
        if (s1 == s2 && s2 == s3 && s3 == s4) {
            return true;
        }
        return false;
    }

    /*
* returns true of false based upon if quadrilateral has congruent consecutive
* sides.
     */
 /*
* returns area of the quadrilateral, in order to do this you may want to check
* this link: https://www.youtube.com/watch?v=JVZud7ZBEKg OR You may want to use
* Heron's Formula, in this case you will treat quadrilateral as two triangles
* and find length of the diagonal.
     */
// returns slope of the line formed by points L and N
    public Rational sideSlope(Point L, Point N) {
        double xDiff = L.getX() - N.getX();
        double yDiff = L.getY() - N.getY();
        Rational r = new Rational(yDiff, xDiff);
        return r;
    }

    public double sideLength(Point L, Point N) {
        double xDiff = L.getX() - N.getX();
        double yDiff = L.getY() - N.getY();
// Calculate the length of the perpendicular using the distance formula
        double length = Math.sqrt(xDiff * xDiff + yDiff * yDiff);
        return length;
    }
// returns perimeter of a quadrilateral

    public double perimeter() {
        double side1 = A.distanceTo(B);
        double side2 = B.distanceTo(C);
        double side3 = C.distanceTo(D);
        double side4 = D.distanceTo(A);
// Return the sum of the distances as the perimeter
        return side1 + side2 + side3 + side4;
    }
// Method to calculate the area of a quadrilateral

    public double area() {
// Calculate the diagonal length and the length of the perpendiculars
        double side1 = sideLength(A, B);
        double side2 = sideLength(B, C);
        double side3 = sideLength(C, D);
        double side4 = sideLength(D, A);
        double side5 = sideLength(A, C);
// Calculate the semiperimeter of each triangle formed by the quadrilateral
        double s1 = (side1 + side2 + side5) / 2;
        double s2 = (side5 + side4 + side3) / 2;
// Calculate the area of each triangle using Heron's formula
        double area1 = Math.sqrt(s1 * (s1 - side1) * (s1 - side2) * (s1 - side5));
        double area2 = Math.sqrt(s2 * (s2 - side5) * (s2 - side4) * (s2 - side3));
// Return the sum of the areas of the two triangles
        return area1 + area2;
    }

    /*
* Classify quadrilateral as parallelogram, rectangle, rhombus, square or
* trapezoid. write code below for this method
     */
    public String classify() {
        if (isParallelogram()) {
// Check if the quadrilateral is a rectangle
            if (isRectangle()) {
                return "RECTANGLE";
            } // Check if the quadrilateral is a rhombus
            else if (isRhombus()) {
                return "RHOMBUS";
            } // Check if the uadrilateral is a square
            else if (isSquare()) {
                return "SQUARE";
            } // If the quadrilateral is not a rectangle, rhombus, or square, it is a
            // parallelogram
            else if (isParallelogram()) {
                return "PARALLELOGRAM";
            }
        } // If the quadrilateral is not a parallelogram or kite, it is a trapezoid
        else {
            return "TRAPEZOID";
        }
        return "normal";
    }

    public String getType() {
        return type;
    }

    private void initSquare() {
        genA();
        genB();
        double diffofx = A.getX() - B.getX();
        double diffofy = A.getY() - B.getY();
        double xofC = B.getX() + diffofy;
        double yofC = B.getY() - diffofx;
        C = new Point(xofC, yofC);
        double xofD = xofC + diffofx;
        double yofD = yofC + diffofy;
        D = new Point(xofD, yofD);
    }

    private void initRectangle() {
        genA();
        genC();
        B = new Point(C.getX(), A.getY());
        D = new Point(A.getX(), C.getY());
    }

    private void initParallelogram() {
        genA();
        genB();
        genC();
        double xdiff = A.getX() - B.getX();
        double ydiff = A.getY() - B.getY();
        double xofD = C.getX() + xdiff;
        double yofD = C.getY() + ydiff;
        D = new Point(xofD, yofD);
    }

    private void initRhombus() {
        genA();
        genC();
        double dbd = 40; // distance bd distBD
        Rational lac = sideSlope(A, C); // distance of ac mAC
        double lbd = (double) lac.getQ() / lac.getP(); // slope of bd mBD
        double diffofx = Math.sqrt(Math.pow(dbd / 2, 2.0) / (1 + Math.pow(lbd, 2.0)));
        double diffofy = diffofx * lbd;
        Point midP = A.midPoint(C); // Intersection point of AC and BD.
        double xofB = midP.getX() + diffofx;
        double yofB = midP.getY() - diffofy;
        double xofD = midP.getX() - diffofx;
        double yofD = midP.getY() + diffofy;
        B = new Point(xofB, yofB);
        D = new Point(xofD, yofD);
    }

    private void initTrapezoid() {
        genA();
        genB();
        genC();
        double dab = A.distanceTo(B);
        double dcd = (dab == 30 ? 50 : 30);
        Rational mRational = sideSlope(A, B);
        double slope = (double) mRational.getP() / mRational.getQ();
        double diffofx = Math.sqrt(Math.pow(dcd, 2) / (Math.pow(slope, 2) + 1));
        double diffofy = diffofx * slope;
        double x = C.getX() - diffofx;
        double y = C.getY() - diffofy;
        D = new Point(x, y);
    }

    /*
* should return coordinates of 4 corners Area: Perimeter: Type:
     */
    public String toString() {
        return "A: " + A + "\t\tB: " + B + "\nC: " + C + "\tD: " + D;
    }
}
