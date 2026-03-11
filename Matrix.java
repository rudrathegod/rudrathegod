package finalProjectMatricesOperations;

import java.util.*;


public class Matrix {

    static Scanner scn = new Scanner(System.in);
    static Matrix result;

    private int rows;
    private int columns;
    private int[][] matrix; 

    public Matrix() {
        rows = 0;
        columns = 0;
        matrix = new int[rows][columns];
        
    }

    public Matrix(int r, int c) {
        rows = r;
        columns = c;
        matrix = new int[rows][columns];

        for (int y = 0; y < getRows(); y++) {
            for (int z = 0; z < getColumns(); z++) {
                matrix[y][z] = (int) (Math.random() * 9) + 1;
            }
        }
        
    }

    public Matrix(int r, int c, int[][] alteredMatrix) {
        rows = r;
        columns = c;
        matrix = alteredMatrix;
    }
    

    public int getRows() {
        return rows;
    }

    public int getColumns() {
        return columns;
    }

    public int[][] getMatrix() {
        return matrix;
    }

    public int getValue(int r, int c) {
        return matrix[r][c];
    }

    public String toString() {

        String x = "";

        for (int y = 0; y < getRows(); y++) {

            x += "[";

            for (int z = 0; z < getColumns(); z++) {

                x += "" + matrix[y][z];

                if (z < getColumns() - 1) {
                    x += ", ";
                }
            }
            x += "]";
            if (y < getRows() - 1) {
                x += "\n";
            }
        }

        return x;
    }
    

    public static void pln(String s) {
        System.out.println(s);
    }

    // Void Operation Methods

    public static void MatrixAddition(Matrix a, Matrix b) {

        int[][] tempA = a.getMatrix();
        int[][] tempB = b.getMatrix();

        int[][] z = new int[a.getRows()][a.getColumns()];

        if ((tempA.length != tempB.length) || (tempA[0].length != tempB[0].length)) {
            pln("Not possible to add these two Matrices due to them not having the same dimensions...");
        } else {

            for (int row = 0; row < tempA.length; row++) {
                for (int col = 0; col < tempA[0].length; col++) {
                    z[row][col] = tempA[row][col] + tempB[row][col];
                }
            }

            result = new Matrix(a.getRows(), a.getColumns(), z);

            pln("The Sum of the two matrices is...\n" + result);

        }

    }

    public static void MatrixSubtraction(Matrix a, Matrix b) {

        int[][] tempA = a.getMatrix();
        int[][] tempB = b.getMatrix();

        int[][] z = new int[a.getRows()][a.getColumns()];

        if ((tempA.length != tempB.length) || (tempA[0].length != tempB[0].length)) {
            pln("Not possible to subtract these two Matrices due to them not having the same dimensions...");
        } else {

            for (int row = 0; row < tempA.length; row++) {
                for (int col = 0; col < tempA[0].length; col++) {
                    z[row][col] = tempA[row][col] - tempB[row][col];
                }
            }

            result = new Matrix(a.getRows(), a.getColumns(), z);

            pln("The Difference of the two matrices is...\n" + result);

        }

    }

    public static void ScalarMultiplication(Matrix a, Matrix b) {

        int[][] tempA = a.getMatrix();
        int[][] tempB = b.getMatrix();

        int[][] resultA = new int[a.getRows()][a.getColumns()];
        int[][] resultB = new int[b.getRows()][b.getColumns()];

        pln("What Scalar or real number would you like to multiply (Only Integers)");
        int scalar = scn.nextInt();

        pln("Which Matrix would you like to use to multiply by the Scalar value?\n"
                + "You may only choose between Matrix 1 or Matrix 2. You cannot choose both\n" + "1. Matrix One\n"
                + "2. Matrix Two");

        int choice = scn.nextInt();

        if (choice == 1) {

            for (int row = 0; row < tempA.length; row++) {
                for (int col = 0; col < tempA[0].length; col++) {
                    resultA[row][col] = scalar * tempA[row][col];
                }
            }

            result = new Matrix(a.getRows(), a.getColumns(), resultA);
            pln("The Product of the scalar and the matrix is...\n" + result);

        } else if (choice == 2) {

            for (int row = 0; row < tempB.length; row++) {
                for (int col = 0; col < tempB[0].length; col++) {
                    resultB[row][col] = scalar * tempB[row][col];
                }
            }

            result = new Matrix(b.getRows(), b.getColumns(), resultB);
            pln("The Product of the scalar and the matrix is...\n" + result);

        }

    }

    public static void MatrixMultiplication(Matrix a, Matrix b) {

        int[][] tempA = a.getMatrix();
        int[][] tempB = b.getMatrix();

        int[][] product = new int[a.getRows()][b.getColumns()];

        if (a.getColumns() != b.getRows()) {
            pln("Not Possible to multiply these two matrices together "
                    + "since # of columns in first matrix has to be equal to # of rows in the second matrix");
            return;
        } else if (a.getColumns() == b.getRows()) {

            for (int i = 0; i < a.getRows(); i++) {
                for (int j = 0; j < b.getColumns(); j++) {
                    for (int k = 0; k < a.getColumns(); k++) {
                        product[i][j] += tempA[i][k] * tempB[k][j];
                    }
                }
            }

            result = new Matrix(a.getRows(), b.getColumns(), product);
            pln("The Product of The Two Matrices is...\n" + result);

        }

    }

    public static void MatrixTranspose(Matrix a, Matrix b) {

        int[][] tempA = a.getMatrix();
        int[][] tempB = b.getMatrix();

        int[][] resultA = new int[a.getColumns()][a.getRows()];
        int[][] resultB = new int[b.getColumns()][b.getRows()];

        pln("Which Matrix would you like to use to take the transpose of?\n"
                + "You may only choose between Matrix 1 or Matrix 2. You cannot choose both\n" + "1. Matrix One\n"
                + "2. Matrix Two");

        int choice = scn.nextInt();

        if (choice == 1) {

            resultA = transposeMatrix(tempA);

            result = new Matrix(a.getColumns(), a.getRows(), resultA);
            pln("The transpose of this Matrix is...\n" + result);

        } else if (choice == 2) {

            resultB = transposeMatrix(tempB);

            result = new Matrix(b.getColumns(), b.getRows(), resultB);
            pln("The transpose of this Matrix is...\n" + result);

        }

    }

    private static int[][] transposeMatrix(int[][] matrix) {
        int rows = matrix.length;
        int cols = matrix[0].length;
        int[][] transposed = new int[cols][rows];

        for (int i = 0; i < rows; i++) {
            for (int j = 0; j < cols; j++) {
                transposed[j][i] = matrix[i][j];
            }
        }

        return transposed;
    }

    public static void MatrixDeterminant(Matrix a, Matrix b) {

        pln("Which Matrix would you like to use to take the determinant of?\n"
                + "You may only choose between Matrix 1 or Matrix 2. You cannot choose both\n" + "1. Matrix One\n"
                + "2. Matrix Two");

        int choice = scn.nextInt();

        if (choice == 1) {

            if ((a.getRows() != a.getColumns()) || (a.getRows() * a.getColumns() > 100)) {
                pln("Error: Not possible to take determinant of this matrix since it is not a square matrix");
                return;
            } else {
                int determinant = calculateDeterminant(a.getMatrix());
                pln("Determinant of Matrix One: " + determinant);

            }

        } else if (choice == 2) {

            if ((b.getRows() != b.getColumns()) || (b.getRows() * b.getColumns() > 100)) {
                pln("Error: Not possible to take determinant of this matrix since it is not a square matrix");
                return;
            } else {
                int determinant = calculateDeterminant(b.getMatrix());
                pln("Determinant of Matrix Two: " + determinant);
            }

        }

    }

    private static int calculateDeterminant(int[][] matrix) {
        int n = matrix.length;

        if (n == 1) {
            return matrix[0][0];
        }

        if (n == 2) {
            return (matrix[0][0] * matrix[1][1]) - (matrix[0][1] * matrix[1][0]);
        }

        int determinant = 0;

        for (int i = 0; i < n; i++) {
            int[][] subMatrix = getSubMatrix(matrix, 0, i);
            determinant += Math.pow(-1, i) * matrix[0][i] * calculateDeterminant(subMatrix);
        }

        return determinant;
    }

    private static int[][] getSubMatrix(int[][] matrix, int excludingRow, int excludingCol) {
        int n = matrix.length;
        int[][] subMatrix = new int[n - 1][n - 1];
        int r = -1;

        for (int i = 0; i < n; i++) {
            if (i == excludingRow) {
                continue;
            }
            r++;
            int c = -1;
            for (int j = 0; j < n; j++) {
                if (j == excludingCol) {
                    continue;
                }
                subMatrix[r][++c] = matrix[i][j];
            }
        }

        return subMatrix;
    }

    public static void MatrixCoFactor(Matrix a, Matrix b) {

        pln("Which Matrix would you like to use to take the cofactor of?\n"
                + "You may only choose between Matrix 1 or Matrix 2. You cannot choose both\n" + "1. Matrix One\n"
                + "2. Matrix Two");

        int choice = scn.nextInt();

        int[][] r = a.getMatrix();
        int[][] rb = b.getMatrix();

        if (choice == 1) {

            int rows = a.getRows();
            int cols = a.getColumns();
            if (rows != cols) {
                pln("Error: Cofactor matrix can only be calculated for square matrices.");
                return;
            }

            if (rows == 2 && cols == 2) {

                int[][] gh = new int[a.getRows()][a.getColumns()];
                gh[0][0] = r[1][1];
                gh[1][1] = r[0][0];
                gh[0][1] = r[0][1] * -1;
                gh[1][0] = r[1][0] * -1;

                result = new Matrix(a.getRows(), a.getColumns(), gh);

                pln("The Cofactor of the matrix is...\n" + result);

            } else {

            int[][] cofactorMatrix = new int[rows][cols];

            for (int i = 0; i < rows; i++) {
                for (int j = 0; j < cols; j++) {
                    int[][] minor = getSubMatrix(a.getMatrix(), i, j);
                    cofactorMatrix[i][j] = (int) Math.pow(-1, i + j) * calculateDeterminant(minor);
                }
            }

            result = new Matrix(a.getRows(), a.getColumns(), cofactorMatrix);

            pln("The Cofactor of the matrix is...\n" + result);
            
            }

        } else if (choice == 2) {

            int rows = b.getRows();
            int cols = b.getColumns();
            if (rows != cols) {
                pln("Error: Cofactor matrix can only be calculated for square matrices.");
                return;
            } else if (rows == 2 && cols == 2) {

                int[][] gh = new int[b.getRows()][b.getColumns()];
                gh[0][0] = rb[1][1];
                gh[1][1] = rb[0][0];
                gh[0][1] = rb[0][1] * -1;
                gh[1][0] = rb[1][0] * -1;

                result = new Matrix(a.getRows(), a.getColumns(), gh);

                pln("The Cofactor of the matrix is...\n" + result);

            } else { 
                int[][] cofactorMatrix = new int[rows][cols];
            

            for (int i = 0; i < rows; i++) {
                for (int j = 0; j < cols; j++) {
                    int[][] minor = getSubMatrix(b.getMatrix(), i, j);
                    cofactorMatrix[i][j] = (int) Math.pow(-1, i + j) * calculateDeterminant(minor);
                }
            }

            result = new Matrix(b.getRows(), b.getColumns(), cofactorMatrix);

            pln("The Cofactor of the matrix is...\n" + result);
            
            }

        }

    }

    public static void MatrixInverse(Matrix a, Matrix b) {

        pln("Which Matrix would you like to use to take the Inverse of?\n"
                + "You may only choose between Matrix 1 or Matrix 2. You cannot choose both\n" + "1. Matrix One\n"
                + "2. Matrix Two");

        int choice = scn.nextInt();

        if (choice == 1) {

            int determinant = calculateDeterminant(a.getMatrix());
            
            int rows = a.getRows();
            int cols = a.getColumns();

            if (rows != cols) {
                pln("Error: Inverse can only be calculated for square matrices.");
                return;
            } else if (determinant == 0) {
                pln("Error: Determinant is 0 and 1/0 yields Arithmetic error.");
                return;
            } else {

            int[][] cofactorMatrix = new int[rows][cols];
            for (int i = 0; i < rows; i++) {
                for (int j = 0; j < cols; j++) {
                    int[][] minor = getSubMatrix(a.getMatrix(), i, j);
                    cofactorMatrix[i][j] = (int) Math.pow(-1, i + j) * calculateDeterminant(minor);
                }
            }
            

            int[][] adjugateMatrix = transposeMatrix(cofactorMatrix);

            double[][] inverseMatrix = new double[rows][cols];
            for (int i = 0; i < rows; i++) {
                for (int j = 0; j < cols; j++) {
                    inverseMatrix[i][j] = adjugateMatrix[i][j] / (double) determinant;
                }
            }
            
            int[][] d = new int[rows][cols];

            for (int i = 0; i < inverseMatrix.length; i++) {
                for (int j = 0; j < inverseMatrix[0].length; j++) {
                    d[i][j] = (int) inverseMatrix[i][j];
                }
            }
            

            result = new Matrix(a.getRows(), a.getColumns(), d);

            pln("The Inverse of the matrix is...\n" + result);
            
            }

        } else if (choice == 2) {

            int rows = b.getRows();
            int cols = b.getColumns();

            if (rows != cols) {
                pln("Error: Inverse can only be calculated for square matrices.");
                return;
            }

            int determinant = calculateDeterminant(b.getMatrix());
            if (determinant == 0) {
                pln("Error: 1/0 is undefined");
                return;
            }

            int[][] cofactorMatrix = new int[rows][cols];
            for (int i = 0; i < rows; i++) {
                for (int j = 0; j < cols; j++) {
                    int[][] minor = getSubMatrix(b.getMatrix(), i, j);
                    cofactorMatrix[i][j] = (int) Math.pow(-1, i + j) * calculateDeterminant(minor);
                }
            }

            int[][] adjugateMatrix = transposeMatrix(cofactorMatrix);

            double[][] inverseMatrix = new double[rows][cols];
            for (int i = 0; i < rows; i++) {
                for (int j = 0; j < cols; j++) {
                    inverseMatrix[i][j] = adjugateMatrix[i][j] / (double) determinant;
                }
            }
            
            int[][] d = new int[rows][cols];

            for (int i = 0; i < inverseMatrix.length; i++) {
                for (int j = 0; j < inverseMatrix[0].length; j++) {
                    d[i][j] = (int) inverseMatrix[i][j];
                }
            }


            result = new Matrix(b.getRows(), b.getColumns(), d);

            pln("The Inverse of the matrix is...\n" + result);

        }

    }

}
