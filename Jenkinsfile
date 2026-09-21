pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps { checkout scm }
        }
        stage('Hello') {
            steps {
                echo "Finance Portfolio - branch: ${env.BRANCH_NAME}"
                sh 'ls -la'
            }
        }
    }
}
