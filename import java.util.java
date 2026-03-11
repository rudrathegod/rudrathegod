
import java.util.*;


public class MatrixRunner extends Matrix { // Made Runner a subclass so it has access to all of Matrix's methods

    static Scanner scn = new Scanner(System.in); // To take user input 
    static Matrix a, b; 

    public static void main(String[] args) {

        
        boolean again = true; // Keep initial condition as user wants to keep asking

        // Start of First Matrix
        pln("How do you want to make your first matrix?\n");
        int choice = StartMenu(); // First ask user if they want random matrix or computer-generated

        if (choice == 1) {
            ComputerGeneratedMatrix(1); // If they choose option 1 - randomly generate nums
        } else if (choice == 2) {
            ManualMatrix(1); // If they chose option 2 - let them manually enter values
        }

        pln("Matrix 1: ");
        pln("");
        pln("" + a); // Use toString method to print out the matrix 

        pln("-------------------------------------------------------------");
        // End of First Matrix

        // Start of Second Matrix
        pln("How do you want to make your second matrix?\n");
        choice = StartMenu(); // Repeat same process again for second matrix 

        if (choice == 1) {
            ComputerGeneratedMatrix(2);
        } else if (choice == 2) {
            ManualMatrix(2);
        }

        pln("Matrix 2: ");
        pln("");
        pln("" + b); // Use toString method to print out the matrix 
        pln("-------------------------------------------------------------");
        pln("");
        // End of Second Matrix

        while (again) { // Keep repeating unless user quits

            pln("With the two Matrices created before, What operation would you like to perform...");

            choice = OperationsMenu(); // Display what operations would user like to perform 
            if (choice == 1) {
                MatrixAddition(a, b);
            } else if (choice == 2) {
                MatrixSubtraction(a, b);
            } else if (choice == 3) {
                ScalarMultiplication(a, b);
            } else if (choice == 4) {
                MatrixMultiplication(a, b);
            } else if (choice == 5) {
                MatrixDeterminant(a, b);
            } else if (choice == 6) {
                MatrixCoFactor(a, b);
            } else if (choice == 7) {
                MatrixTranspose(a, b);
            } else if (choice == 8) {
                MatrixInverse(a, b);
            }

            pln("-------------------------------------------------------------");

            choice = EndMenu();
            if (choice == 0) { // If they want to quit, end program
                again = false;
                scn.close();
                pln("Goodbye: This Project was really innovative & Exciting! "
                        + "I had a fun time doing it & had a great CSA Experience!" + " See you again soon!");
                break;

            }

        }

    }

    public static int StartMenu() {

        int x = 3;

        while (x != 1 && x != 2) {
            pln("1. Randomly Generated Matrix by Computer \n" + "2. Manually Enter all values into Matrix ");
            x = scn.nextInt();
            if (x != 1 && x != 2) {
                pln("Invalid Input. Try again...");
            }

        }

        return x;

    }

    public static int OperationsMenu() {

        int x = 10;

        while (x != 1 && x != 2 && x != 3 && x != 4 && x != 5 && x != 6 && x != 7 && x != 8) {
            pln("1. Matrix Addition \n" + "2. Matrix Subtraction \n" + "3. Scalar Multiplication \n"
                    + "4. Matrix Multiplication \n" + "5. Determinant \n" + "6. Cofactor Matrix \n" + "7. Transpose \n"
                    + "8. Inverse \n" + "");

            x = scn.nextInt();
            if (x != 1 && x != 2 && x != 3 && x != 4 && x != 5 && x != 6 && x != 7 && x != 8) {
                pln("Invalid Input. Try again...");
            }

        }

        return x;

    }

    public static int EndMenu() {

        int x = 2;

        while (x != 0 && x != 1) {

            pln("1: Want to preform another operation with the same Matrices?");
            pln("0: Quit");

            x = scn.nextInt();

            if (x != 0 && x != 1) {
                pln("Invalid Input. Try again...");
            }

        }

        return x;

    }

    public static void ComputerGeneratedMatrix(int n) {

        pln("A Matrix with more than 100 elements is not allowed: Max size of matrix is 10 rows and 10 columns...");

        int r = 11, c = 11;

        while (r < 1 || r > 10 || c < 1 || c > 10 || r * c > 100) {
            pln("Enter # of rows for the matrix");
            r = scn.nextInt();
            pln("Enter # of columns for the matrix");
            c = scn.nextInt();

            if (r < 1 || r > 10 || c < 1 || c > 10 || r * c > 100) {
                pln("Invalid Matrix Size. Try again...");
            }
        }

        if (n == 1) {
            a = new Matrix(r, c);
        } else if (n == 2) {
            b = new Matrix(r, c);
        }

    }

    public static void ManualMatrix(int n) {

        pln("A Matrix with more than 100 elements is not allowed: Max size of matrix is 10 rows and 10 columns...");

        int r = 11, c = 11;

        while (r < 1 || r > 10 || c < 1 || c > 10 || r * c > 100) {
            pln("Enter # of rows for the matrix");
            r = scn.nextInt();
            pln("Enter # of columns for the matrix");
            c = scn.nextInt();

            if (r < 1 || r > 10 || c < 1 || c > 10 || r * c > 100) {
                pln("Invalid Matrix Size. Try again...");
            }
        }

        if (n == 1) {

            int[][] temp = new int[r][c];

            pln("Enter the elements of the matrix row by row:");

            for (int i = 0; i < r; i++) {
                for (int j = 0; j < c; j++) {
                    pln("Element [" + i + "][" + j + "]: ");
                    temp[i][j] = scn.nextInt();
                }
            }

            a = new Matrix(r, c, temp);

        } else if (n == 2) {

            int[][] temp = new int[r][c];

            pln("Enter the elements of the matrix row by row:");

            for (int i = 0; i < r; i++) {
                for (int j = 0; j < c; j++) {
                    pln("Element [" + i + "][" + j + "]: ");
                    temp[i][j] = scn.nextInt();
                }
            }

            b = new Matrix(r, c, temp);

        }

    }
    
    

}
