exports.handler = async function(event, context) {
  // Your app logic here
  return {
    statusCode: 200,
    body: JSON.stringify({ message: "Connected to Streamlit app" })
  };
};