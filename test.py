import requests, json

def test_api_response():
    url = "http://localhost:3000/api/search?query=onimai-i-m-now-your-sister"
    response = requests.get(url)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    print("Full response:\n", json.dumps(data, indent=2))  # Debug print

    # Extract results
    if isinstance(data, dict):
        releases = data.get("results") or data.get("data") or []
    elif isinstance(data, list):
        releases = data
    else:
        raise AssertionError(f"Unexpected response structure: {type(data)}")

    assert len(releases) > 0, "No results found for your query"

    # Print first result safely
    first = releases[0]
    print("First release object:\n", json.dumps(first, indent=2))

    # Example: check expected keys
    for key in ["id", "title", "image"]:
        if key not in first:
            print(f"Warning: '{key}' not in first release")

if __name__ == "__main__":
    test_api_response()
