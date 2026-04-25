import random
import time
import logging
from flask import jsonify

logger = logging.getLogger(__name__)

def init_system_test_routes(app):
    @app.route('/system-test/traffic')
    def simulate_traffic():
        """Simulates normal traffic with various status codes."""
        codes = [200, 200, 200, 201, 204, 404]
        code = random.choice(codes)
        logger.info(f"Simulated traffic request received. Returning {code}")
        return f"Simulated traffic with status {code}", code

    @app.route('/system-test/error')
    def simulate_error():
        """Simulates a server-side error."""
        try:
            logger.error("Simulating a critical system error for monitoring validation.")
            # Intentionally causing a division by zero to trigger an actual exception if desired, 
            # or just return 500.
            1 / 0
        except Exception as e:
            logger.exception("Caught simulated error: %s", str(e))
            return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

    @app.route('/system-test/warning')
    def simulate_warning():
        """Simulates a system warning."""
        logger.warning("Simulated warning: High CPU usage detected (not really).")
        return "Warning logged!", 200

    @app.route('/system-test/slow')
    def simulate_slow_request():
        """Simulates a high-latency request."""
        delay = random.uniform(0.5, 3.0)
        logger.info(f"Simulating slow request with delay: {delay:.2f}s")
        time.sleep(delay)
        return f"Slow request finished after {delay:.2f}s", 200

    @app.route('/system-test/logs')
    def test_logs():
        """Comprehensive log level test."""
        logger.debug("This is a DEBUG log.")
        logger.info("This is an INFO log.")
        logger.warning("This is a WARNING log.")
        logger.error("This is an ERROR log.")
        logger.critical("This is a CRITICAL log.")
        return "All log levels fired!", 200

    @app.route('/system-test/simulate')
    def simulate_complex_load():
        """Simulates a mix of logs, latency, and random errors."""
        iterations = random.randint(3, 8)
        results = []
        for i in range(iterations):
            choice = random.random()
            if choice < 0.6:
                logger.info(f"Simulation step {i}: Normal operation")
                results.append("Normal")
            elif choice < 0.8:
                logger.warning(f"Simulation step {i}: Minor bottleneck detected")
                results.append("Warning")
                time.sleep(random.uniform(0.1, 0.5))
            else:
                logger.error(f"Simulation step {i}: Partial failure in subsystem")
                results.append("Error")
        
        return jsonify({
            "status": "Simulation complete",
            "steps": results,
            "total_iterations": iterations
        }), 200
