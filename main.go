package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/joho/godotenv"
)

var (
	mpesaBaseAPIURL, shortCode, consumerKey, consumerSecret, passkey, callbackURL string
	password, timestamp                                                           string
	logFile                                                                       = "transaction_log.json"
)

func init() {
	// Load environment variables from .env file
	if err := godotenv.Load(); err != nil {
		log.Fatalf("Error loading .env file: %v", err)
	}

	// Validate and assign required environment variables
	requiredVars := []struct {
		env   *string
		key   string
		label string
	}{
		{&mpesaBaseAPIURL, "MPESA_BASE_API_URL", "Base API URL"},
		{&shortCode, "SHORTCODE", "Short Code"},
		{&consumerKey, "CONSUMER_KEY", "Consumer Key"},
		{&consumerSecret, "CONSUMER_SECRET", "Consumer Secret"},
		{&passkey, "PASSKEY", "Passkey"},
		{&callbackURL, "CALLBACK_URL", "Callback URL"},
	}
	for _, v := range requiredVars {
		if *v.env = os.Getenv(v.key); *v.env == "" {
			log.Fatalf("Environment variable %s (%s) is not set", v.key, v.label)
		}
	}

	// Generate timestamp and encoded password for M-Pesa transaction authorization
	timestamp = time.Now().Format("20060102150405")
	password = base64.StdEncoding.EncodeToString([]byte(shortCode + passkey + timestamp))
}

// getMpesaToken generates an OAuth token for M-Pesa API access.
func getMpesaToken() (string, error) {
	url := fmt.Sprintf("%s/oauth/v1/generate?grant_type=client_credentials", mpesaBaseAPIURL)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", fmt.Errorf("creating token request: %w", err)
	}
	req.SetBasicAuth(consumerKey, consumerSecret)

	client := &http.Client{Timeout: time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("requesting token: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := ioutil.ReadAll(resp.Body)
		return "", fmt.Errorf("token request failed, status: %s, response: %s", resp.Status, body)
	}

	var result struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("decoding token response: %w", err)
	}
	return result.AccessToken, nil
}

// logToFile appends transaction data with a timestamp to a JSON log file.
func logToFile(data map[string]interface{}) {
	data["timestamp"] = time.Now().Format(time.RFC3339)
	entry, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		log.Printf("Error encoding log entry: %v", err)
		return
	}

	// Open log file in append mode to prevent overwriting
	file, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("Error opening log file: %v", err)
		return
	}
	defer file.Close()

	if _, err = file.Write(append(entry, '\n')); err != nil {
		log.Printf("Error writing to log file: %v", err)
	}
}

// sendSTKPush initiates an STK push request and logs the response.
func sendSTKPush() (string, error) {
	token, err := getMpesaToken()
	if err != nil {
		return "", fmt.Errorf("failed to get token: %w", err)
	}

	headers := map[string]string{"Authorization": "Bearer " + token}
	phoneNumber := "254746554245"
	amount := 1
	transRef := "Testing Daraja API"

	payload := map[string]interface{}{
		"BusinessShortCode": shortCode,
		"Password":          password,
		"Timestamp":         timestamp,
		"TransactionType":   os.Getenv("TRANS_TYPE"),
		"Amount":            amount,
		"PartyA":            phoneNumber,
		"PartyB":            os.Getenv("PARTY_B"),
		"PhoneNumber":       phoneNumber,
		"CallBackURL":       callbackURL,
		"AccountReference":  transRef,
		"TransactionDesc":   "Testing Daraja API",
	}

	url := fmt.Sprintf("%s/mpesa/stkpush/v1/processrequest", mpesaBaseAPIURL)
	jsonResp, err := postJSON(url, payload, headers)
	if err != nil {
		return "", fmt.Errorf("STK push request failed: %w", err)
	}

	logToFile(map[string]interface{}{"type": "STK Push Response", "data": jsonResp})

	checkoutRequestID, ok := jsonResp["CheckoutRequestID"].(string)
	if !ok {
		return "", fmt.Errorf("checkout request ID missing in response")
	}
	return checkoutRequestID, nil
}

// queryStatus queries the current status of the STK push transaction.
func queryStatus(checkoutRequestID string) (bool, error) {
	token, err := getMpesaToken()
	if err != nil {
		return false, fmt.Errorf("failed to get token: %w", err)
	}

	headers := map[string]string{"Authorization": "Bearer " + token}
	payload := map[string]interface{}{
		"BusinessShortCode": shortCode,
		"Password":          password,
		"Timestamp":         timestamp,
		"CheckoutRequestID": checkoutRequestID,
	}

	url := fmt.Sprintf("%s/mpesa/stkpushquery/v1/query", mpesaBaseAPIURL)
	jsonResp, err := postJSON(url, payload, headers)
	if err != nil {
		return false, fmt.Errorf("status query failed: %w", err)
	}

	logToFile(map[string]interface{}{"type": "Query Status Response", "data": jsonResp})

	resultCode, ok := jsonResp["ResultCode"].(string)
	if !ok {
		return false, fmt.Errorf("result code missing in response")
	}

	resultCodeInt, err := strconv.Atoi(resultCode)
	if err != nil {
		return false, fmt.Errorf("converting ResultCode to int: %w", err)
	}

	resultDesc := jsonResp["ResultDesc"].(string)

	switch resultCodeInt {
	case 0:
		fmt.Println("Transaction successful.")
		return true, nil
	case 1:
		return false, fmt.Errorf("transaction failed: %s", resultDesc)
	case 500:
		fmt.Println("Transaction is still being processed. Retrying in 30 seconds.")
		return false, nil
	default:
		return false, fmt.Errorf("unknown result code: %d, description: %s", resultCodeInt, resultDesc)
	}
}

// postJSON makes a POST request with JSON payload and headers, returning JSON response.
func postJSON(url string, payload map[string]interface{}, headers map[string]string) (map[string]interface{}, error) {
	data, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encoding payload: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(data))
	if err != nil {
		return nil, fmt.Errorf("creating request: %w", err)
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("performing request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := ioutil.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error, status: %s, body: %s", resp.Status, string(body))
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decoding response: %w", err)
	}

	return result, nil
}

func main() {
	// Initiate the STK push and poll its status periodically until completion
	checkoutRequestID, err := sendSTKPush()
	if err != nil {
		log.Fatalf("Error initiating STK push: %v", err)
	}

	startTime := time.Now()
	for {
		if time.Since(startTime) >= 90*time.Second { // 1.5 minutes
			fmt.Println("Timeout reached. Exiting.")
			return
		}

		success, err := queryStatus(checkoutRequestID)
		if err != nil {
			log.Printf("Error querying status: %v", err)
			time.Sleep(30 * time.Second)
			return
		}
		if success {
			fmt.Println("Transaction completed.")
			return
		}
		time.Sleep(30 * time.Second)
	}
}
